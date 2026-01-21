from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import (
    Sum, F, ExpressionWrapper, DecimalField, Value
)
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from core.forms import (
    OdemeForm, HakedisForm, Depo, FaturaGirisForm, FaturaKalemFormSet
)
from core.models import (
    Tedarikci, Fatura, Odeme, Kategori, GiderKategorisi,
    Hakedis, SatinAlma, FaturaKalem, DepoHareket
)
from core.utils import tcmb_kur_getir, to_decimal
from .guvenlik import yetki_kontrol


@login_required
def finans_dashboard(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    guncel_kurlar = tcmb_kur_getir()
    kur_usd = to_decimal(guncel_kurlar.get('USD', 1))
    kur_eur = to_decimal(guncel_kurlar.get('EUR', 1))
    kur_gbp = to_decimal(guncel_kurlar.get('GBP', 1))

    def cevir(tl_tutar):
        return {
            'usd': (tl_tutar / kur_usd).quantize(Decimal('0.00')),
            'eur': (tl_tutar / kur_eur).quantize(Decimal('0.00')),
            'gbp': (tl_tutar / kur_gbp).quantize(Decimal('0.00'))
        }

    imalat_maliyeti = Decimal('0.00')
    imalat_labels, imalat_data = [], []
    kategoriler = Kategori.objects.prefetch_related('kalemler__teklifler').all()

    toplam_kalem_sayisi = 0
    dolu_kalem_sayisi = 0

    for kat in kategoriler:
        kat_toplam = Decimal('0.00')
        for kalem in kat.kalemler.all():
            toplam_kalem_sayisi += 1
            onayli = kalem.teklifler.filter(durum='onaylandi').first()
            if onayli:
                kat_toplam += to_decimal(onayli.toplam_fiyat_tl)
                dolu_kalem_sayisi += 1
            else:
                bekleyenler = kalem.teklifler.filter(durum='beklemede')
                if bekleyenler.exists():
                    en_dusuk = min(bekleyenler, key=lambda t: t.toplam_fiyat_tl)
                    kat_toplam += to_decimal(en_dusuk.toplam_fiyat_tl)
                    dolu_kalem_sayisi += 1

        if kat_toplam > 0:
            imalat_labels.append(kat.isim)
            imalat_data.append(float(kat_toplam))
            imalat_maliyeti += kat_toplam

    harcama_tutari = Decimal('0.00')
    gider_labels, gider_data = [], []

    for gk in GiderKategorisi.objects.all():
        tutar_tl = sum(to_decimal(h.tl_tutar) for h in gk.harcamalar.all())
        if tutar_tl > 0:
            gider_labels.append(gk.isim)
            gider_data.append(float(tutar_tl))
            harcama_tutari += tutar_tl

    # Dashboard Borç Hesaplaması (Dinamik & Hassas)

    hakedis_borcu = (
        Hakedis.objects
        .filter(onay_durumu=True)
        .aggregate(t=Sum('odenecek_net_tutar'))['t']
        or Decimal('0.00')
    )

    # Fatura borcu kalemlerden (KDV dahil)
    fatura_borcu = (
        FaturaKalem.objects
        .annotate(
            kdv_oran=F('kdv_orani'),
            satir_toplam=ExpressionWrapper(
                F('miktar') * F('birim_fiyat') * (
                    Value(Decimal('1.00')) + (F('kdv_oran') / Value(Decimal('100.00')))
                ),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )
        .aggregate(t=Sum('satir_toplam'))['t']
        or Decimal('0.00')
    )

    toplam_odenen = (
        Odeme.objects
        .aggregate(t=Sum('tutar'))['t']
        or Decimal('0.00')
    )

    kalan_borc = (to_decimal(hakedis_borcu) + to_decimal(fatura_borcu)) - to_decimal(toplam_odenen)

    oran = int((dolu_kalem_sayisi / toplam_kalem_sayisi) * 100) if toplam_kalem_sayisi else 0
    context = {
        'imalat_maliyeti': imalat_maliyeti,
        'harcama_tutari': harcama_tutari,
        'genel_toplam': imalat_maliyeti + harcama_tutari,
        'kalan_borc': kalan_borc,
        'oran': oran,
        'doviz_genel': cevir(imalat_maliyeti + harcama_tutari),
        'imalat_labels': imalat_labels,
        'imalat_data': imalat_data,
        'gider_labels': gider_labels,
        'gider_data': gider_data,
        'kurlar': guncel_kurlar,
    }
    return render(request, 'finans_dashboard.html', context)


@login_required
def finans_ozeti(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    finans_verisi = []
    genel_borc = Decimal('0.00')
    genel_odenen = Decimal('0.00')

    # Fatura borcu: FaturaKalem satırlarından hesaplanır (KDV dahil)
    kalem_qs = (
        FaturaKalem.objects
        .select_related('fatura', 'fatura__tedarikci')
        .annotate(
            satir_toplam=ExpressionWrapper(
                F('miktar') * F('birim_fiyat') * (
                    Value(Decimal('1.00')) + (F('kdv_orani') / Value(Decimal('100.00')))
                ),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )
    )

    # tedarikci bazlı fatura toplamları
    fatura_toplamlari = {
        row['fatura__tedarikci']: to_decimal(row['toplam'])
        for row in (
            kalem_qs.values('fatura__tedarikci')
            .annotate(toplam=Sum('satir_toplam'))
        )
        if row['fatura__tedarikci']
    }

    # ödemeler tedarikci bazlı
    odeme_toplamlari = {
        row['tedarikci']: to_decimal(row['toplam'])
        for row in (
            Odeme.objects.values('tedarikci').annotate(toplam=Sum('tutar'))
        )
        if row['tedarikci']
    }

    tedarikciler = Tedarikci.objects.all().order_by('firma_unvani')
    for ted in tedarikciler:
        borc = to_decimal(fatura_toplamlari.get(ted.id, Decimal('0.00')))
        odenen = to_decimal(odeme_toplamlari.get(ted.id, Decimal('0.00')))
        bakiye = borc - odenen

        if borc > 0 or odenen > 0:
            finans_verisi.append({
                'id': ted.id,
                'firma': ted.firma_unvani,
                'borc': borc,
                'odenen': odenen,
                'bakiye': bakiye,
            })
            genel_borc += borc
            genel_odenen += odenen

    return render(request, 'finans_ozeti.html', {
        'veriler': finans_verisi,
        'toplam_borc': genel_borc,
        'toplam_odenen': genel_odenen,
        'toplam_bakiye': genel_borc - genel_odenen,
    })


@login_required
def hakedis_ekle(request, siparis_id):
    """
    Bu view daha önce yanlışlıkla finans_ozeti() fonksiyonunun altına (return'den sonra)
    yapışmıştı. Orada ölü kod olur ve URL çağrısı patlar.
    Burada gerçek view olarak düzeltildi.
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)

    mevcut_toplam_ilerleme = (
        Hakedis.objects
        .filter(satinalma=siparis)
        .aggregate(t=Sum('tamamlanma_orani'))['t']
        or Decimal('0.00')
    )

    # kalan kapasite = 100 - mevcut
    kalan_kapasite = (Decimal('100.00') - to_decimal(mevcut_toplam_ilerleme)).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    if kalan_kapasite < 0:
        kalan_kapasite = Decimal('0.00')

    if request.method == 'POST':
        form = HakedisForm(request.POST)
        if form.is_valid():
            hakedis = form.save(commit=False)
            hakedis.satinalma = siparis  # ilişkiyi ata

            yeni_oran = to_decimal(hakedis.tamamlanma_orani)

            # %100 kontrol
            if (to_decimal(mevcut_toplam_ilerleme) + yeni_oran) > Decimal('100.00'):
                kalan = (Decimal('100.00') - to_decimal(mevcut_toplam_ilerleme)).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                if kalan < 0:
                    kalan = Decimal('0.00')
                messages.error(request, f"⛔ Hata: Toplam ilerleme %100'ü geçemez! Kalan kapasite: %{kalan}")
                return render(request, 'hakedis_ekle.html', {
                    'form': form,
                    'siparis': siparis,
                    'mevcut_toplam': mevcut_toplam_ilerleme,
                    'kalan_kapasite': kalan,
                })

            # teklifte kdv varsa set et
            try:
                hakedis.kdv_orani = siparis.teklif.kdv_orani
            except Exception:
                pass

            hakedis.onay_durumu = True

            try:
                hakedis.save()

                # Sipariş miktar alanları varsa güncelle
                try:
                    toplam_is = to_decimal(siparis.toplam_miktar)
                    yapilan_miktar = (toplam_is * yeni_oran) / Decimal('100.00')
                    siparis.teslim_edilen = to_decimal(siparis.teslim_edilen) + yapilan_miktar
                    siparis.faturalanan_miktar = to_decimal(siparis.faturalanan_miktar) + yapilan_miktar
                    siparis.save()
                except Exception:
                    pass

                messages.success(request, f"✅ %{yeni_oran} oranındaki hakediş onaylandı.")
                return redirect('siparis_listesi')

            except Exception as e:
                messages.error(request, f"Hesaplama hatası oluştu: {str(e)}")
                return render(request, 'hakedis_ekle.html', {
                    'form': form,
                    'siparis': siparis,
                    'mevcut_toplam': mevcut_toplam_ilerleme,
                    'kalan_kapasite': kalan_kapasite,
                })
    else:
        form = HakedisForm(initial={
            'tarih': timezone.now().date(),
            'hakedis_no': Hakedis.objects.filter(satinalma=siparis).count() + 1,
            'kdv_orani': getattr(getattr(siparis, "teklif", None), "kdv_orani", None)
        })

    return render(request, 'hakedis_ekle.html', {
        'form': form,
        'siparis': siparis,
        'mevcut_toplam': mevcut_toplam_ilerleme,
        'kalan_kapasite': kalan_kapasite,
    })


@login_required
def odeme_yap(request):
    if not yetki_kontrol(request.user, ['MU_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    tedarikci_id = request.GET.get('tedarikci_id') or request.POST.get('tedarikci')
    acik_kalemler = []
    secilen_tedarikci = None
    toplam_borc = Decimal('0.00')

    if tedarikci_id:
        try:
            secilen_tedarikci = Tedarikci.objects.get(id=tedarikci_id)

            # Hakedişler (Kuruş hassasiyeti için 0.01 filtresi)
            hakedisler = Hakedis.objects.filter(
                onay_durumu=True,
                satinalma__teklif__tedarikci=secilen_tedarikci
            ).annotate(
                kalan=ExpressionWrapper(
                    F('odenecek_net_tutar') - F('fiili_odenen_tutar'),
                    output_field=DecimalField()
                )
            ).filter(kalan__gt=0.01)

            for hk in hakedisler:
                acik_kalemler.append({
                    'id': hk.id, 'tip': 'hakedis', 'tarih': hk.tarih,
                    'aciklama': f"Hakediş #{hk.hakedis_no}",
                    'kalan_tutar': hk.kalan
                })
                toplam_borc += hk.kalan

            # Malzemeler
            malzemeler = SatinAlma.objects.filter(
                teklif__tedarikci=secilen_tedarikci,
                teklif__malzeme__isnull=False
            ).exclude(teslimat_durumu='bekliyor')

            for mal in malzemeler:
                miktar = to_decimal(mal.teslim_edilen)
                fiyat = to_decimal(mal.teklif.birim_fiyat)
                kur = to_decimal(mal.teklif.kur_degeri)
                kdv = to_decimal(mal.teklif.kdv_orani)

                tutar = (miktar * fiyat * kur) * (Decimal('1') + (kdv / Decimal('100')))
                odenen = to_decimal(mal.fiili_odenen_tutar)
                kalan = (tutar - odenen).quantize(Decimal('0.01'))

                if kalan > 0.01:
                    acik_kalemler.append({
                        'id': mal.id, 'tip': 'malzeme',
                        'tarih': mal.created_at.date(),
                        'aciklama': f"{mal.teklif.malzeme.isim}",
                        'kalan_tutar': kalan
                    })
                    toplam_borc += kalan
        except Exception:
            pass

    if request.method == 'POST':
        form = OdemeForm(request.POST)
        if form.is_valid():
            odeme = form.save(commit=False)
            try:
                ham_tutar = str(form.cleaned_data['tutar']).replace(',', '.')
                odeme.tutar = Decimal(ham_tutar).quantize(Decimal('0.01'))
            except Exception:
                odeme.tutar = Decimal('0.00')

            odeme.save()

            dagitilacak = odeme.tutar
            secilenler = request.POST.getlist('secilen_kalem')

            # Borç Dağıtma Algoritması (Kuruş Hassasiyetli)
            for secim in secilenler:
                if dagitilacak <= 0:
                    break
                try:
                    tip, id_str = secim.split('_')
                    if tip == 'hakedis':
                        hk = Hakedis.objects.get(id=id_str)
                        borc = (to_decimal(hk.odenecek_net_tutar) - to_decimal(hk.fiili_odenen_tutar)).quantize(Decimal('0.01'))
                        odenecek_kisim = min(dagitilacak, borc)
                        hk.fiili_odenen_tutar = (to_decimal(hk.fiili_odenen_tutar) + odenecek_kisim).quantize(Decimal('0.01'))
                        hk.save()
                        dagitilacak -= odenecek_kisim

                    elif tip == 'malzeme':
                        mal = SatinAlma.objects.get(id=id_str)
                        t = (
                            to_decimal(mal.teslim_edilen)
                            * to_decimal(mal.teklif.birim_fiyat)
                            * to_decimal(mal.teklif.kur_degeri)
                        ) * (Decimal('1') + (to_decimal(mal.teklif.kdv_orani) / Decimal('100')))
                        borc = (t.quantize(Decimal('0.01')) - to_decimal(mal.fiili_odenen_tutar)).quantize(Decimal('0.01'))
                        odenecek_kisim = min(dagitilacak, borc)
                        mal.fiili_odenen_tutar = (to_decimal(mal.fiili_odenen_tutar) + odenecek_kisim).quantize(Decimal('0.01'))
                        mal.save()
                        dagitilacak -= odenecek_kisim
                except Exception:
                    pass

            messages.success(request, "✅ Ödeme kaydedildi.")
            return redirect(f"/odeme/yap/?tedarikci_id={odeme.tedarikci.id}")
    else:
        form = OdemeForm(initial={'tarih': timezone.now().date(), 'tedarikci': secilen_tedarikci})

    return render(request, 'odeme_yap.html', {
        'form': form,
        'tedarikciler': Tedarikci.objects.all(),
        'secilen_tedarikci': secilen_tedarikci,
        'acik_kalemler': acik_kalemler,
        'toplam_borc': toplam_borc
    })


@login_required
def cari_ekstre(request, tedarikci_id):
    tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
    hareketler = []

    # Hakedişler
    for h in Hakedis.objects.filter(satinalma__teklif__tedarikci=tedarikci, onay_durumu=True):
        hareketler.append({
            'tarih': h.tarih,
            'aciklama': f"Hakediş #{h.hakedis_no}",
            'borc': to_decimal(h.odenecek_net_tutar),
            'alacak': Decimal('0')
        })

    # Malzemeler
    for m in SatinAlma.objects.filter(
        teklif__tedarikci=tedarikci,
        teklif__malzeme__isnull=False
    ).exclude(teslimat_durumu='bekliyor'):
        try:
            miktar = to_decimal(m.teslim_edilen)
            fiyat = to_decimal(m.teklif.birim_fiyat)
            kur = to_decimal(m.teklif.kur_degeri)
            tutar = miktar * fiyat * kur

            if tutar > 0:
                hareketler.append({
                    'tarih': m.created_at.date(),
                    'aciklama': m.teklif.malzeme.isim,
                    'borc': tutar,
                    'alacak': Decimal('0')
                })
        except Exception:
            pass

    # Ödemeler
    for o in Odeme.objects.filter(tedarikci=tedarikci):
        hareketler.append({
            'tarih': o.tarih,
            'aciklama': f"Ödeme ({o.odeme_turu})",
            'borc': Decimal('0'),
            'alacak': to_decimal(o.tutar)
        })

    hareketler.sort(key=lambda x: x['tarih'])
    bakiye = Decimal('0.00')
    for h in hareketler:
        bakiye += (h['borc'] - h['alacak'])
        h['bakiye'] = bakiye

    return render(request, 'cari_ekstre.html', {
        'tedarikci': tedarikci,
        'hareketler': hareketler
    })


@login_required
def get_tedarikci_bakiye(request, tedarikci_id):
    try:
        tedarikci = Tedarikci.objects.get(id=tedarikci_id)
        hakedis_borc = Hakedis.objects.filter(
            satinalma__teklif__tedarikci=tedarikci, onay_durumu=True
        ).aggregate(t=Sum('odenecek_net_tutar'))['t'] or Decimal('0')
        odenen = Odeme.objects.filter(
            tedarikci=tedarikci
        ).aggregate(t=Sum('tutar'))['t'] or Decimal('0')

        return JsonResponse({
            'success': True,
            'kalan_bakiye': float(hakedis_borc - odenen)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def odeme_sil(request, odeme_id):
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    odeme = get_object_or_404(Odeme, id=odeme_id)
    tedarikci_id = odeme.tedarikci.id

    odeme.delete()

    messages.warning(request, "🗑️ Ödeme kaydı silindi, cari bakiye güncellendi.")
    # ✅ url adı projende 'tedarikci_ekstresi' diye geçiyor
    return redirect('tedarikci_ekstresi', tedarikci_id=tedarikci_id)


@login_required
def fatura_girisi(request, siparis_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)

    # Hizmet işi ise ayrı ekrana yönlendir
    try:
        if getattr(siparis.teklif, "is_kalemi", None):
            return redirect('hizmet_faturasi_giris', siparis_id=siparis.id)
    except Exception:
        pass

    tedarikci = siparis.teklif.tedarikci

    # ✅ Sanal depo (Vendor) bul
    sanal_depo = Depo.objects.filter(is_sanal=True).first()
    if not sanal_depo:
        messages.error(request, "⛔ Sanal depo bulunamadı. Admin > Depo'dan is_sanal=True olan bir depo oluşturmalısın.")
        return redirect("siparis_listesi")

    if request.method == "POST":
        form = FaturaGirisForm(request.POST, request.FILES, satinalma=siparis)
        formset = FaturaKalemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    # 1) Fatura başlığı
                    fatura = form.save(commit=False)
                    fatura.tedarikci = tedarikci
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

                        # ✅ (ASIL İŞ) Fatura kalemi kaydolunca SANAL DEPOYA GİRİŞ hareketi oluştur
                        DepoHareket.objects.get_or_create(
                            ref_type="FATURA_KALEM",
                            ref_id=k.id,
                            ref_direction="IN",
                            malzeme=k.malzeme,
                            depo=sanal_depo,
                            defaults={
                                "siparis": siparis,
                                "tarih": fatura.tarih or timezone.now().date(),
                                "islem_turu": "giris",
                                "miktar": k.miktar,
                                "tedarikci": tedarikci,
                                "aciklama": f"Fatura #{fatura.fatura_no} (Sanal depoya giriş)",
                            }
                        )

                    # Silinenleri sil
                    for obj in formset.deleted_objects:
                        obj.delete()

                    if gercek_kalem_sayisi == 0:
                        raise ValueError("En az 1 kalem girilmelidir.")

                    # 3) Sipariş faturalanan_miktar güncelle (sipariş malzemesi kadar)
                    try:
                        sip_malzeme = getattr(siparis.teklif, "malzeme", None)
                        if sip_malzeme:
                            eslesen = (
                                FaturaKalem.objects
                                .filter(fatura=fatura, malzeme=sip_malzeme)
                                .aggregate(s=Sum("miktar"))["s"]
                                or Decimal("0")
                            )
                            siparis.faturalanan_miktar = (
                                to_decimal(siparis.faturalanan_miktar) + to_decimal(eslesen)
                            )
                            siparis.save(update_fields=["faturalanan_miktar"])
                    except Exception:
                        pass

                messages.success(request, f"✅ Fatura kaydedildi ve sanal depoya giriş yapıldı. Genel Toplam: {fatura.genel_toplam}")
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
def hizmet_faturasi_giris(request, siparis_id):
    """
    SADECE HİZMETLER İÇİN: Depo sormayan, stok hareketi yapmayan sade fatura ekranı.
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)

    # Yanlışlıkla malzeme siparişi ile buraya gelinirse geri gönder
    if siparis.teklif.malzeme:
        messages.warning(request, "Malzeme siparişleri için standart fatura girişi yapmalısınız.")
        return redirect('fatura_girisi', siparis_id=siparis.id)

    if request.method == 'POST':
        try:
            fatura_no = request.POST.get('fatura_no')
            tarih = request.POST.get('tarih')
            tutar = to_decimal(request.POST.get('tutar'))

            miktar_str = request.POST.get('miktar')
            if miktar_str:
                miktar = to_decimal(miktar_str)
            else:
                miktar = Decimal('1')

            dosya = request.FILES.get('dosya')

            fatura = Fatura(
                satinalma=siparis,
                fatura_no=fatura_no,
                tarih=tarih,
                miktar=miktar,
                tutar=tutar,
                depo=None,
                dosya=dosya
            )
            fatura.save()

            messages.success(request, f"✅ Hizmet faturası (#{fatura_no}) cariye işlendi.")
            return redirect('siparis_listesi')

        except Exception as e:
            messages.error(request, f"Hata oluştu: {str(e)}")
            return render(request, 'hizmet_faturasi.html', {'siparis': siparis})

    return render(request, 'hizmet_faturasi.html', {'siparis': siparis})


@login_required
def odeme_dashboard(request):
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    # Hakediş Toplamı (Sadece onaylılar)
    hakedis_toplam = (
        Hakedis.objects
        .filter(onay_durumu=True)
        .aggregate(toplam=Sum('odenecek_net_tutar'))['toplam']
        or Decimal('0.00')
    )

    # Malzeme Borcu (teslim edilen miktar üzerinden)
    malzeme_borcu = Decimal('0.00')
    siparisler = (
        SatinAlma.objects
        .filter(teklif__malzeme__isnull=False)
        .select_related('teklif')
    )

    for sip in siparisler:
        miktar = to_decimal(sip.teslim_edilen)
        fiyat = to_decimal(sip.teklif.birim_fiyat)
        kur = to_decimal(sip.teklif.kur_degeri)
        kdv_orani = to_decimal(sip.teklif.kdv_orani)

        ara_toplam = miktar * fiyat * kur
        kdvli_toplam = ara_toplam * (Decimal('1') + (kdv_orani / Decimal('100')))
        malzeme_borcu += kdvli_toplam

    toplam_odenen = (
        Odeme.objects
        .aggregate(toplam=Sum('tutar'))['toplam']
        or Decimal('0.00')
    )

    context = {
        'hakedis_toplam': hakedis_toplam,
        'malzeme_borcu': malzeme_borcu,
        'toplam_borc': (hakedis_toplam + malzeme_borcu) - toplam_odenen,
        'son_hakedisler': Hakedis.objects.order_by('-tarih')[:5],
        'son_alimlar': SatinAlma.objects.filter(teklif__malzeme__isnull=False).order_by('-created_at')[:5],
    }
    return render(request, 'odeme_dashboard.html', context)


@login_required
def cek_takibi(request):
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    bugun = timezone.now().date()
    cekler = Odeme.objects.filter(odeme_turu='cek').order_by('vade_tarihi')

    toplam_risk = cekler.aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0.00')

    context = {
        'gecikmisler': cekler.filter(vade_tarihi__lt=bugun),
        'yaklasanlar': cekler.filter(vade_tarihi__gte=bugun, vade_tarihi__lte=bugun + timezone.timedelta(days=30)),
        'ileri_tarihliler': cekler.filter(vade_tarihi__gt=bugun + timezone.timedelta(days=30)),
        'toplam_risk': toplam_risk,
        'bugun': bugun
    }
    return render(request, 'cek_takibi.html', context)


@login_required
def cek_durum_degistir(request, odeme_id):
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    odeme = Odeme.objects.filter(id=odeme_id, odeme_turu='cek').first()
    if not odeme:
        messages.error(request, "Çek kaydı bulunamadı.")
        return redirect('cek_takibi')

    messages.info(request, "Çek durumu değiştirme özelliği henüz aktif değil.")
    return redirect('cek_takibi')
