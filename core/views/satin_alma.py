from decimal import Decimal, ROUND_HALF_UP

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django import forms
from django.utils import timezone
from django.db import transaction
from django.db.models import F

from core.models import SatinAlma, Depo, DepoHareket, Fatura, DepoTransfer
from core.forms import FaturaGirisForm
from .guvenlik import yetki_kontrol
from core.utils import to_decimal


# -------------------------------
# Helpers
# -------------------------------
def _to_dec(val, default="0"):
    try:
        if val is None or val == "":
            return Decimal(str(default))
        if isinstance(val, Decimal):
            return val
        return Decimal(str(val).replace(",", "."))
    except Exception:
        return Decimal(str(default))


def _hesapla_fatura_tutari(teklif, miktar):
    """
    Tekliften KDV dahil nihai tutarı hesaplar.
    - birim_fiyat * miktar
    - para birimi kur_degeri ile TL'ye çevirir
    - teklif.kdv_dahil_mi False ise KDV ekler
    """
    miktar = _to_dec(miktar, "0")
    birim_fiyat = _to_dec(getattr(teklif, "birim_fiyat", None), "0")
    kur = _to_dec(getattr(teklif, "kur_degeri", None), "1")

    tutar = birim_fiyat * miktar * kur

    if not getattr(teklif, "kdv_dahil_mi", False):
        kdv_orani = _to_dec(getattr(teklif, "kdv_orani", None), "0")
        tutar = tutar * (Decimal("1") + (kdv_orani / Decimal("100")))

    return tutar.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# -------------------------------
# Views
# -------------------------------
@login_required
def siparis_listesi(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')

    tum_siparisler = (
        SatinAlma.objects
        .filter(teklif__durum='onaylandi')
        .select_related('teklif__tedarikci', 'teklif__malzeme', 'teklif__is_kalemi')
        .prefetch_related('depo_hareketleri', 'depo_hareketleri__depo')
        .order_by('-created_at')
    )

    bekleyenler, bitenler = [], []
    for siparis in tum_siparisler:
        if siparis.sanal_depoda_bekleyen > 0 or siparis.kalan_fatura_miktar > 0:
            bekleyenler.append(siparis)
        else:
            bitenler.append(siparis)

    return render(request, 'siparis_listesi.html', {
        'bekleyenler': bekleyenler,
        'bitenler': bitenler
    })


@login_required
def mal_kabul(request):
    if not yetki_kontrol(request.user, ['SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparisler = (
        SatinAlma.objects
        .filter(teklif__durum='onaylandi')
        .select_related('teklif__tedarikci', 'teklif__malzeme')
        .order_by('-created_at')
    )

    aktif_siparisler = [s for s in siparisler if s.sanal_depoda_bekleyen > 0]
    fiziksel_depolar = Depo.objects.filter(is_sanal=False)

    return render(request, 'mal_kabul.html', {
        'siparisler': aktif_siparisler,
        'depolar': fiziksel_depolar
    })


@login_required
def fatura_girisi(request, siparis_id):
    """
    ALIŞ FATURASI GİRİŞİ (ÇOK KALEM)
    - Tedarikçi siparişten gelir, formdan gelen değer dikkate alınmaz.
    - Toplamlar FaturaKalem.save() içinde otomatik hesaplanıyor (model tarafında recalc var).
    - Siparişin faturalanan_miktar alanı: bu faturadaki sipariş malzemesi kalemleri kadar artar.
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)

    # Hizmet işi ise ayrı ekrana yönlendir (sende bu view finans.py'de var)
    try:
        if getattr(siparis.teklif, "is_kalemi", None):
            return redirect('hizmet_faturasi_giris', siparis_id=siparis.id)
    except Exception:
        pass

    tedarikci = siparis.teklif.tedarikci

    if request.method == "POST":
        form = FaturaGirisForm(request.POST, request.FILES, satinalma=siparis)
        formset = FaturaKalemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    # 1) Fatura başlığı
                    fatura = form.save(commit=False)
                    fatura.tedarikci = tedarikci
                    # Fatura modelinde satinalma alanı varsa set et:
                    if hasattr(fatura, "satinalma"):
                        fatura.satinalma = siparis
                    fatura.save()

                    # 2) Kalemleri kaydet
                    formset.instance = fatura
                    kalemler = formset.save(commit=False)

                    gercek_kalem_sayisi = 0
                    for k in kalemler:
                        if not getattr(k, "malzeme_id", None):
                            continue
                        if to_decimal(getattr(k, "miktar", 0)) <= 0:
                            continue
                        k.fatura = fatura
                        k.save()
                        gercek_kalem_sayisi += 1

                    for obj in formset.deleted_objects:
                        obj.delete()

                    if gercek_kalem_sayisi == 0:
                        raise ValueError("En az 1 kalem girilmelidir.")

                    # 3) Sipariş faturalanan_miktar güncelle (siparişin malzemesi kadar)
                    try:
                        sip_malzeme = getattr(siparis.teklif, "malzeme", None)
                        if sip_malzeme:
                            eslesen = (
                                FaturaKalem.objects
                                .filter(fatura=fatura, malzeme=sip_malzeme)
                                .aggregate(s=Sum("miktar"))["s"]
                                or Decimal("0")
                            )
                            if hasattr(siparis, "faturalanan_miktar"):
                                siparis.faturalanan_miktar = (
                                    to_decimal(siparis.faturalanan_miktar) + to_decimal(eslesen)
                                )
                                siparis.save(update_fields=["faturalanan_miktar"])
                    except Exception:
                        pass

                messages.success(request, f"✅ Fatura kaydedildi. Genel Toplam: {fatura.genel_toplam}")
                return redirect("siparis_listesi")

            except Exception as e:
                messages.error(request, f"⛔ Kayıt sırasında hata: {str(e)}")
        else:
            messages.error(request, "⛔ Form doğrulama hatası var. Kırmızı kutudaki hatalara bak.")

        return render(request, "fatura_girisi.html", {
            "siparis": siparis,
            "form": form,
            "formset": formset,
        })

    # GET
    form = FaturaGirisForm(initial={"tarih": timezone.now().date()}, satinalma=siparis)
    formset = FaturaKalemFormSet()

    return render(request, "fatura_girisi.html", {
        "siparis": siparis,
        "form": form,
        "formset": formset,
    })


@login_required
def mal_kabul_islem(request, siparis_id):
    if not yetki_kontrol(request.user, ['SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)
    fiziksel_depolar = Depo.objects.filter(is_sanal=False)

    if request.method == 'POST':
        miktar = to_decimal(request.POST.get('miktar'))
        hedef_depo_id = request.POST.get('depo')
        hedef_depo = get_object_or_404(Depo, id=hedef_depo_id)

        if miktar > siparis.sanal_depoda_bekleyen:
            messages.error(request, f"Hata: Sanal depoda sadece {siparis.sanal_depoda_bekleyen} birim mal var!")
            return redirect('mal_kabul')

        sanal_depo = Depo.objects.filter(is_sanal=True).first()
        if not sanal_depo:
            messages.error(request, "Sanal depo bulunamadı. Lütfen önce sanal depo tanımlayın.")
            return redirect('mal_kabul')

        DepoTransfer.objects.create(
            malzeme=siparis.teklif.malzeme,
            miktar=miktar,
            kaynak_depo=sanal_depo,
            hedef_depo=hedef_depo,
            bagli_siparis=siparis,
            tarih=timezone.now().date(),
            aciklama=f"Satın alma mal kabulü: {siparis.id}"
        )

        messages.success(request, f"✅ {miktar} birim mal başarıyla {hedef_depo.isim} deposuna alındı.")
        return redirect('mal_kabul')

    return render(request, 'mal_kabul_islem.html', {
        'siparis': siparis,
        'depolar': fiziksel_depolar
    })


@login_required
def siparis_detay(request, siparis_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)
    hareketler = DepoHareket.objects.filter(siparis=siparis).order_by('-tarih', '-id')
    faturalar = siparis.faturalar.all().order_by('-tarih', '-id')

    return render(request, 'siparis_detay.html', {
        'siparis': siparis,
        'hareketler': hareketler,
        'faturalar': faturalar
    })


@login_required
def fatura_sil(request, fatura_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    fatura = get_object_or_404(Fatura, id=fatura_id)
    siparis = fatura.satinalma

    # güvenli azalt
    SatinAlma.objects.filter(id=siparis.id).update(
        faturalanan_miktar=F('faturalanan_miktar') - fatura.miktar
    )

    # ilgili stok girişini sil (NOT: sen modelde ref ile yazıyorsan daha sağlamı ref üzerinden silmektir)
    DepoHareket.objects.filter(
        siparis=siparis,
        miktar=fatura.miktar,
        islem_turu='giris',
        aciklama__icontains=fatura.fatura_no
    ).delete()

    fatura.delete()
    messages.warning(request, f"🗑️ {fatura.fatura_no} nolu fatura ve ilgili stok girişi silindi.")
    return redirect('siparis_detay', siparis_id=siparis.id)
