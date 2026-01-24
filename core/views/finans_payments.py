from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, F, DecimalField, Value
from django.http import JsonResponse
from django.db import transaction
from django.db.models.functions import Coalesce
import json

# Modeller
from core.models import Fatura, Hakedis, Harcama, Odeme, Tedarikci
from core.views.guvenlik import yetki_kontrol



from core.models import (
    SatinAlma, Hakedis, Odeme, Tedarikci, Fatura, IsKalemi, Teklif, Malzeme, Harcama
)

# OdemeDagitim opsiyonel (migration yapılmadıysa dosya patlamasın)
try:
    from core.models import OdemeDagitim
except Exception:
    OdemeDagitim = None

from core.forms import HakedisForm, OdemeForm
from core.views.guvenlik import yetki_kontrol
from core.utils import to_decimal, tcmb_kur_getir
from core.services.finans_payments import PaymentService


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================
def clean_currency_input(value_str):
    """
    Frontend'den gelen '1.250,50' (TR) veya '1250.50' (US) formatlarını
    doğru şekilde Python Decimal formatına çevirir.
    """
    if not value_str:
        return Decimal("0.00")

    if isinstance(value_str, (int, float, Decimal)):
        return to_decimal(value_str)

    value_str = str(value_str).strip()

    if "." in value_str and "," in value_str:
        last_dot = value_str.rfind(".")
        last_comma = value_str.rfind(",")

        if last_comma > last_dot:
            value_str = value_str.replace(".", "").replace(",", ".")
        else:
            value_str = value_str.replace(",", "")
    elif "," in value_str:
        value_str = value_str.replace(",", ".")

    try:
        return Decimal(value_str)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _pick_attr(obj, names):
    """Objede listelenen alan adlarından ilk bulunanı döndürür (yoksa None)."""
    for n in names:
        if hasattr(obj, n):
            val = getattr(obj, n)
            if val not in [None, ""]:
                return val
    return None


def _normalize_currency(pb):
    if not pb:
        return "TRY"
    pb = str(pb).strip().upper()
    if pb == "TL":
        return "TRY"
    return pb


def get_smart_exchange_rate(obj, guncel_kurlar):
    """
    Fatura / Hakediş için doğru kuru ve para birimini bulur.

    KRİTİK KURAL:
      - Hakediş sistemimizde TL tutulur. Hakediş için asla kur uygulanmaz.
        -> Dönüş her zaman ("TRY", 1.0)

    Fatura için öncelik sırası:
      1) Objede direkt para_birimi ve kur alanları (varsa)
      2) Satınalma -> teklif üzerinden para birimi/kur
      3) En son TCMB güncel kuru

    Dönüş: (para_birimi, kur_degeri)
    """
    # ✅ 0) Hakediş her zaman TL (kur yok)
    try:
        # import içeride: circular import riskini azaltır
        from core.models import Hakedis
        if isinstance(obj, Hakedis):
            return "TRY", Decimal("1.0")
    except Exception:
        pass

    pb = "TRY"
    kur = Decimal("1.0")

    # 1) Objede direkt para birimi (varsa)
    direct_pb = _pick_attr(obj, ["para_birimi", "currency", "doviz_cinsi", "doviz"])
    if direct_pb:
        pb = _normalize_currency(direct_pb)

    # 2) Objede para birimi yoksa / TRY ise, satinalma.teklif para birimine bak
    if pb == "TRY":
        if hasattr(obj, "satinalma") and obj.satinalma and getattr(obj.satinalma, "teklif", None):
            pb = _normalize_currency(getattr(obj.satinalma.teklif, "para_birimi", "TRY"))

    # Para birimi TRY ise kur 1.0
    if pb == "TRY":
        return "TRY", Decimal("1.0")

    # 3) Objede direkt kur (varsa)
    direct_kur = _pick_attr(obj, ["kur_degeri", "kur", "fx_rate", "doviz_kuru"])
    if direct_kur:
        try:
            k = to_decimal(direct_kur)
            if k > Decimal("0.1"):
                return pb, k
        except Exception:
            pass

    # 4) Satınalma -> teklif kuru
    if hasattr(obj, "satinalma") and obj.satinalma and getattr(obj.satinalma, "teklif", None):
        teklif = obj.satinalma.teklif
        teklif_kur = _pick_attr(teklif, ["kur_degeri", "kur", "fx_rate"])
        if teklif_kur:
            try:
                k = to_decimal(teklif_kur)
                if k > Decimal("0.1"):
                    return pb, k
            except Exception:
                pass

    # 5) TCMB güncel kuru
    try:
        k = guncel_kurlar.get(pb, Decimal("1.0"))
        k = to_decimal(k)
        if k > Decimal("0.1"):
            return pb, k
    except Exception:
        pass

    return pb, Decimal("1.0")


def _teklif_currency_info_from_hk(hk: Hakedis, guncel_kurlar: dict):
    """
    Hakediş TL tutulsa bile, bilgi amaçlı para birimi/kur göstermek için tekliften okur.
    """
    try:
        teklif = hk.satinalma.teklif if hk.satinalma_id else None
        if not teklif:
            return "TRY", Decimal("1.0")
        pb = _normalize_currency(getattr(teklif, "para_birimi", "TRY"))
        if pb == "TRY":
            return "TRY", Decimal("1.0")
        kur = to_decimal(getattr(teklif, "kur_degeri", None) or guncel_kurlar.get(pb, 1) or 1)
        if kur <= 0:
            kur = Decimal("1.0")
        return pb, kur
    except Exception:
        return "TRY", Decimal("1.0")


def _odeme_dagitim_supported():
    return OdemeDagitim is not None


def _odeme_allocated_ids():
    """
    Allocation bulunan odeme id'lerini döndürür.
    (Çifte saymayı engellemek için kullanıyoruz)
    """
    if not _odeme_dagitim_supported():
        return []
    try:
        return list(OdemeDagitim.objects.values_list("odeme_id", flat=True).distinct())
    except Exception:
        return []


def _paid_tl_for_invoice(fat: Fatura) -> Decimal:
    """
    Bir faturaya yapılan toplam TL ödemeyi döndürür.
    Öncelik: OdemeDagitim varsa onun üzerinden hesaplar.
    Eski sistem: Odeme.fatura üzerinden bağlanan (allocation'sız) ödemeler de dahil edilir.
    """
    toplam = Decimal("0.00")
    allocated_ids = _odeme_allocated_ids()

    # 1) Allocation üzerinden
    if _odeme_dagitim_supported():
        try:
            t = OdemeDagitim.objects.filter(fatura=fat).aggregate(s=Sum("tutar"))["s"] or Decimal("0")
            toplam += to_decimal(t)
        except Exception:
            pass

    # 2) Eski sistem direct ödeme (allocation yoksa)
    try:
        qs = Odeme.objects.filter(fatura=fat)
        if allocated_ids:
            qs = qs.exclude(id__in=allocated_ids)
        t2 = qs.aggregate(s=Sum("tutar"))["s"] or Decimal("0")
        toplam += to_decimal(t2)
    except Exception:
        pass

    return to_decimal(toplam)


def _recalc_invoice_odenen_tutar_orj(fat: Fatura, guncel_kurlar: dict):
    """
    fat.odenen_tutar alanını (ORJ gibi kullanılıyorsa) günceller:
    - Bizim sistem TL ödeme tutuyor
    - Fatura döviz ise: TL / kur ile orj karşılık yazılır (sadece fatura ekranındaki "odenen_tutar" için).
    """
    try:
        pb, kur = get_smart_exchange_rate(fat, guncel_kurlar)
        if pb != "TRY" and kur and to_decimal(kur) > 0:
            paid_tl = _paid_tl_for_invoice(fat)
            fat.odenen_tutar = (to_decimal(paid_tl) / to_decimal(kur)).quantize(Decimal("0.01"))
        else:
            # TL fatura ise, odenen_tutar'ı TL toplam gibi düşünüyorsan burayı paid_tl yapabilirsin.
            # Şimdiki mimaride odenen_tutar zaten fatura tarafında ayrı yönetilebilir.
            fat.odenen_tutar = fat.odenen_tutar or Decimal("0.00")
        fat.save(update_fields=["odenen_tutar"])
    except Exception:
        pass


def _invoice_total_tl(fat: Fatura, guncel_kurlar: dict) -> Decimal:
    """
    KRİTİK KURAL:
    - Fatura.genel_toplam sistemimizde TL tutulur.
    - Bu nedenle ASLA tekrar kur uygulanmaz.
    - Döviz bilgisi sadece "bilgi amaçlı" gösterimde kullanılabilir.
    """
    return to_decimal(fat.genel_toplam).quantize(Decimal("0.01"))


def _invoice_remaining_tl(fat: Fatura, guncel_kurlar: dict) -> Decimal:
    """
    Kalan TL = toplam TL - ödenen TL.
    Kur uygulanmaz.
    """
    total_tl = _invoice_total_tl(fat, guncel_kurlar)
    paid_tl = _paid_tl_for_invoice(fat)
    return max(to_decimal(total_tl) - to_decimal(paid_tl), Decimal("0.00"))


def _hakedis_remaining_tl(hk: Hakedis) -> Decimal:
    """
    Hakediş kalan TL.
    KRİTİK: Hakediş tutarları TL tutulduğu için tekrar kur uygulanmaz.
    """
    kalan_tl = (to_decimal(hk.odenecek_net_tutar) - to_decimal(hk.fiili_odenen_tutar)).quantize(Decimal("0.01"))
    return max(kalan_tl, Decimal("0.00"))


# =========================================================
# VIEW FONKSİYONLARI
# =========================================================
@login_required
def hakedis_ekle(request, siparis_id):
    if not yetki_kontrol(request.user, ["OFIS_VE_SATINALMA", "MUHASEBE_FINANS", "YONETICI"]):
        return redirect("erisim_engellendi")

    siparis = get_object_or_404(SatinAlma, id=siparis_id)
    mevcut_toplam = (
        Hakedis.objects.filter(satinalma=siparis).aggregate(t=Sum("tamamlanma_orani"))["t"]
        or Decimal("0.00")
    )
    kalan_kapasite = Decimal("100.00") - to_decimal(mevcut_toplam)

    if request.method == "POST":
        form = HakedisForm(request.POST)
        if form.is_valid():
            hakedis = form.save(commit=False)
            hakedis.satinalma = siparis
            hakedis.onay_durumu = True
            try:
                PaymentService.hakedis_validasyon(siparis.id, hakedis.tamamlanma_orani)
                hakedis.save()
                PaymentService.siparis_guncelle(siparis, hakedis.tamamlanma_orani)
                messages.success(request, f"✅ %{hakedis.tamamlanma_orani} hakediş onaylandı.")
                return redirect("siparis_listesi")
            except Exception as e:
                messages.error(request, f"Hata: {str(e)}")
    else:
        form = HakedisForm(
            initial={
                "tarih": timezone.now().date(),
                "hakedis_no": Hakedis.objects.filter(satinalma=siparis).count() + 1,
            }
        )

    return render(
        request,
        "hakedis_ekle.html",
        {
            "form": form,
            "siparis": siparis,
            "mevcut_toplam": mevcut_toplam,
            "kalan_kapasite": kalan_kapasite,
        },
    )


@login_required
def odeme_yap(request):
    """
    ÖDEME EKRANI
    - TL ödeme kaydı
    - Döviz faturaları TL karşılığı gösterim (fatura toplam * kur)
    - Hakedişler TL olduğu için KUR tekrar uygulanmaz (kritik düzeltme)
    """
    if not yetki_kontrol(request.user, ["MUHASEBE_FINANS", "YONETICI"]):
        return redirect("erisim_engellendi")

    tedarikci_id = request.GET.get("tedarikci_id") or request.POST.get("tedarikci")
    fatura_id = request.GET.get("fatura_id")

    acik_kalemler = []
    secilen_tedarikci = None
    toplam_guncel_borc_tl = Decimal("0.00")
    guncel_kurlar = tcmb_kur_getir()

    if fatura_id and not tedarikci_id:
        fatura_obj = get_object_or_404(Fatura, id=fatura_id)
        tedarikci_id = fatura_obj.tedarikci.id

    if tedarikci_id:
        try:
            secilen_tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)

            # --- 1) HAKEDİŞLER (TL) ---
            hakedisler = Hakedis.objects.filter(
                satinalma__teklif__tedarikci=secilen_tedarikci,
                onay_durumu=True
            )

            for hk in hakedisler:
                kalan_tl = _hakedis_remaining_tl(hk)
                if kalan_tl > Decimal("0.00"):
                    pb_info, kur_info = _teklif_currency_info_from_hk(hk, guncel_kurlar)
                    orj_hint = None
                    if pb_info != "TRY" and kur_info and kur_info > 0:
                        try:
                            orj_hint = (to_decimal(kalan_tl) / to_decimal(kur_info)).quantize(Decimal("0.01"))
                        except Exception:
                            orj_hint = None

                    aciklama = f"Hakediş #{hk.hakedis_no}"
                    try:
                        if hk.satinalma and hk.satinalma.teklif and hk.satinalma.teklif.is_kalemi:
                            aciklama += f" - {hk.satinalma.teklif.is_kalemi.isim}"
                    except Exception:
                        pass

                    if pb_info != "TRY" and orj_hint is not None:
                        aciklama += (
                            f" <br><span class='badge bg-warning text-dark'>"
                            f"Bilgi: ~{orj_hint:,.2f} {pb_info} (Kur: {kur_info})</span>"
                        )

                    acik_kalemler.append({
                        "id": hk.id,
                        "tip": "Hakedis",
                        "evrak_no": f"Hakediş #{hk.hakedis_no}",
                        "tarih": hk.tarih,
                        "aciklama": aciklama,
                        "tutar_orj": orj_hint,      # bilgi
                        "para_birimi": pb_info,     # bilgi
                        "kur": kur_info,            # bilgi
                        "tutar": kalan_tl,          # ✅ TL (KUR YOK!)
                    })
                    toplam_guncel_borc_tl += kalan_tl

            # --- 2) FATURALAR (TL karşılığı) ---
            faturalar = Fatura.objects.filter(tedarikci=secilen_tedarikci).order_by("tarih", "id")
            for fat in faturalar:
                kalan_tl = _invoice_remaining_tl(fat, guncel_kurlar)
                if kalan_tl > Decimal("0.00"):
                    pb, kur = get_smart_exchange_rate(fat, guncel_kurlar)

                    kalan_orj = None
                    try:
                        kalan_orj = (to_decimal(kalan_tl) / to_decimal(kur)).quantize(Decimal("0.01")) if to_decimal(kur) > 0 else None
                    except Exception:
                        pass

                    aciklama_text = fat.aciklama or ""
                    if pb != "TRY" and kalan_orj is not None:
                        aciklama_text += (
                            f" <br><span class='badge bg-warning text-dark'>"
                            f"Orj: {kalan_orj:,.2f} {pb} (Kur: {kur})</span>"
                        )

                    acik_kalemler.append({
                        "id": fat.id,
                        "tip": "Fatura",
                        "evrak_no": f"Fatura #{fat.fatura_no}",
                        "tarih": fat.tarih,
                        "aciklama": aciklama_text,
                        "tutar_orj": kalan_orj,
                        "para_birimi": pb,
                        "kur": kur,
                        "tutar": kalan_tl,  # TL
                    })
                    toplam_guncel_borc_tl += kalan_tl

        except Exception as e:
            messages.error(request, f"Veri hatası: {str(e)}")

    # --- POST (KAYDET) ---
    if request.method == "POST":
        form = OdemeForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    odeme = form.save(commit=False)
                    if secilen_tedarikci:
                        odeme.tedarikci = secilen_tedarikci

                    raw_tutar = request.POST.get("tutar", "0")
                    odeme.tutar = clean_currency_input(raw_tutar)
                    odeme.para_birimi = "TRY"
                    odeme.save()

                    # Eski davranış: direkt fatura_id geldiyse odeme.fatura bağla (geri uyum)
                    if fatura_id and not odeme.fatura:
                        try:
                            odeme.fatura = Fatura.objects.get(id=int(fatura_id))
                            odeme.save(update_fields=["fatura"])
                        except Exception:
                            pass

                    dagitilacak_tl = to_decimal(odeme.tutar)
                    secilenler = request.POST.getlist("secilen_kalem")

                    if not secilenler and fatura_id:
                        secilenler = [f"Fatura_{fatura_id}"]

                    for secim in secilenler:
                        if dagitilacak_tl <= Decimal("0.00"):
                            break

                        try:
                            tip, id_str = secim.split("_")
                            obj_id = int(id_str)
                        except ValueError:
                            continue

                        if tip == "Hakedis":
                            hk = Hakedis.objects.get(id=obj_id)

                            # ✅ Hakediş TL tutuluyor => TL olarak mahsup et
                            kalan_hk_tl = _hakedis_remaining_tl(hk)
                            if kalan_hk_tl <= Decimal("0.00"):
                                continue

                            pay_tl = min(dagitilacak_tl, kalan_hk_tl).quantize(Decimal("0.01"))

                            hk.fiili_odenen_tutar = (to_decimal(hk.fiili_odenen_tutar) + pay_tl).quantize(Decimal("0.01"))
                            hk.save(update_fields=["fiili_odenen_tutar"])

                            if not odeme.bagli_hakedis:
                                odeme.bagli_hakedis = hk
                                odeme.save(update_fields=["bagli_hakedis"])

                            dagitilacak_tl -= pay_tl

                        elif tip == "Fatura":
                            fat = Fatura.objects.get(id=obj_id)

                            kalan_tl = _invoice_remaining_tl(fat, guncel_kurlar)
                            if kalan_tl <= Decimal("0.00"):
                                continue

                            pay_tl = min(dagitilacak_tl, kalan_tl).quantize(Decimal("0.01"))

                            if _odeme_dagitim_supported():
                                OdemeDagitim.objects.create(
                                    odeme=odeme,
                                    fatura=fat,
                                    tutar=to_decimal(pay_tl),
                                    tarih=odeme.tarih,
                                    aciklama=(odeme.aciklama or ""),
                                )

                            _recalc_invoice_odenen_tutar_orj(fat, guncel_kurlar)

                            if not odeme.fatura:
                                odeme.fatura = fat
                                odeme.save(update_fields=["fatura"])

                            dagitilacak_tl -= pay_tl

                    messages.success(request, f"✅ {odeme.tutar} TL tutarında ödeme işlendi.")
                    
                    # DEĞİŞEN KISIM: Dashboard yerine Yazdırma Onayına git
                    return redirect('islem_sonuc', model_name='odeme', pk=odeme.id)

            except Exception as e:
                messages.error(request, f"Kayıt hatası: {str(e)}")
    else:
        initial_data = {
            "tarih": timezone.now().date(),
            "tedarikci": secilen_tedarikci,
            "para_birimi": "TRY",
        }

        if fatura_id:
            hedef = next(
                (item for item in acik_kalemler if str(item["id"]) == str(fatura_id) and item["tip"] == "Fatura"),
                None,
            )
            if hedef:
                initial_data["tutar"] = hedef["tutar"]
                initial_data["aciklama"] = f"{hedef['evrak_no']} Ödemesi"

        form = OdemeForm(initial=initial_data)

    borc_ozeti = {"TL": toplam_guncel_borc_tl}

    return render(
        request,
        "odeme_yap.html",
        {
            "form": form,
            "tedarikciler": Tedarikci.objects.all().order_by("firma_unvani"),
            "secilen_tedarikci": secilen_tedarikci,
            "acik_kalemler": acik_kalemler,
            "borc_ozeti": borc_ozeti,
            "toplam_borc_tl": toplam_guncel_borc_tl,
        },
    )


@login_required
def avans_mahsup(request, tedarikci_id):
    if not yetki_kontrol(request.user, ["MUHASEBE_FINANS", "YONETICI"]):
        return redirect("erisim_engellendi")

    if not _odeme_dagitim_supported():
        messages.error(request, "Mahsup (avans eşleştirme) için OdemeDagitim modeli eklenmemiş. Önce migration yapılmalı.")
        return redirect("odeme_dashboard")

    tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
    guncel_kurlar = tcmb_kur_getir()

    avanslar = []
    odemeler_qs = Odeme.objects.filter(tedarikci=tedarikci).order_by("tarih", "id")

    for o in odemeler_qs:
        dagitilan = OdemeDagitim.objects.filter(odeme=o).aggregate(s=Sum("tutar"))["s"] or Decimal("0.00")
        dagitilan = to_decimal(dagitilan)

        # fatura bağlı ama hiç dağıtım yoksa avans sayma
        if o.fatura_id and dagitilan <= Decimal("0.00"):
            continue

        kalan = to_decimal(o.tutar) - dagitilan
        if kalan > Decimal("0.01"):
            o.tutar_tl = kalan
            avanslar.append(o)

    faturalar = []
    for fat in Fatura.objects.filter(tedarikci=tedarikci).order_by("tarih", "id"):
        kalan_tl = _invoice_remaining_tl(fat, guncel_kurlar)
        if kalan_tl > Decimal("0.01"):
            faturalar.append({
                "id": fat.id,
                "no": fat.fatura_no,
                "tarih": fat.tarih,
                "aciklama": fat.aciklama or "",
                "kalan_tl": to_decimal(kalan_tl),
            })

    if request.method == "POST":
        try:
            with transaction.atomic():
                odeme_id_raw = request.POST.get("odeme_id")
                if not odeme_id_raw:
                    messages.error(request, "Mahsup hatası: Avans (ödeme) seçilmedi.")
                    return redirect("avans_mahsup", tedarikci_id=tedarikci.id)

                odeme_id = int(odeme_id_raw)
                sec_fatura_ids = request.POST.getlist("fatura_id")

                odeme = get_object_or_404(Odeme, id=odeme_id, tedarikci=tedarikci)

                dagitilan = OdemeDagitim.objects.filter(odeme=odeme).aggregate(s=Sum("tutar"))["s"] or Decimal("0.00")
                kalan_avans = to_decimal(odeme.tutar) - to_decimal(dagitilan)

                if kalan_avans <= Decimal("0.01"):
                    messages.error(request, "Bu ödeme için kullanılabilir avans kalmamış.")
                    return redirect("avans_mahsup", tedarikci_id=tedarikci.id)

                sec_faturalar = Fatura.objects.filter(
                    id__in=sec_fatura_ids,
                    tedarikci=tedarikci
                ).order_by("tarih", "id")

                for fat in sec_faturalar:
                    if kalan_avans <= Decimal("0.01"):
                        break

                    kalan_fatura_tl = _invoice_remaining_tl(fat, guncel_kurlar)
                    if kalan_fatura_tl <= Decimal("0.01"):
                        continue

                    pay = min(kalan_avans, kalan_fatura_tl).quantize(Decimal("0.01"))

                    OdemeDagitim.objects.create(
                        odeme=odeme,
                        fatura=fat,
                        tutar=to_decimal(pay),
                        tarih=timezone.now().date(),
                        aciklama=f"Avans Mahsup (Ödeme #{odeme.id})"
                    )

                    _recalc_invoice_odenen_tutar_orj(fat, guncel_kurlar)
                    kalan_avans -= to_decimal(pay)

                if kalan_avans > Decimal("0.01"):
                    messages.success(request, f"✅ Mahsup tamamlandı. Kalan avans: {kalan_avans:,.2f} TL")
                else:
                    messages.success(request, "✅ Mahsup tamamlandı. Avans tamamen kullanıldı.")

            return redirect("avans_mahsup", tedarikci_id=tedarikci.id)

        except Exception as e:
            messages.error(request, f"Mahsup hatası: {str(e)}")
            return redirect("avans_mahsup", tedarikci_id=tedarikci.id)

    return render(request, "avans_mahsup.html", {
        "tedarikci": tedarikci,
        "avanslar": avanslar,
        "faturalar": faturalar,
    })


@login_required
def finans_dashboard(request):
    """
    PATRON EKRANI: Finansal Özet ve Nakit Akışı
    Mantık: Tahakkuk Esaslı (Accrual Basis)
    - Fabrika Maliyeti = Faturalar (KDV Dahil) + Hakedişler (Brüt+KDV) + Giderler
    - Cari Borç = Maliyet - Ödemeler
    - Yaklaşan Çekler = Vadesi 30 gün içinde olan VE henüz 'Ödendi' işaretlenmemiş çekler.
    """
    if not yetki_kontrol(request.user, ['YONETICI', 'MUHASEBE_FINANS']):
        return redirect('erisim_engellendi')

    # 1. HESAPLAMALAR: TOPLAM MALİYET BİLEŞENLERİ (TL)
    
    # A) Faturalar (Malzeme Alımları) -> KDV Dahil Tutar
    toplam_fatura = Fatura.objects.aggregate(
        t=Coalesce(Sum('genel_toplam'), Decimal('0.00'))
    )['t']

    # B) Hakedişler (Hizmet/Taşeron) -> Brüt Tutar + KDV Tutarı
    hakedis_qs = Hakedis.objects.filter(onay_durumu=True).aggregate(
        t=Coalesce(Sum(F('brut_tutar') + F('kdv_tutari')), Decimal('0.00'))
    )
    toplam_hakedis = hakedis_qs['t']

    # C) Giderler (OPEX - Harcamalar) -> TL Karşılığı
    giderler_listesi = Harcama.objects.all()
    toplam_gider = sum([g.tl_tutar for g in giderler_listesi]) or Decimal('0.00')

    # --- GRAND TOTAL (FABRİKA MALİYETİ) ---
    fabrika_maliyeti = toplam_fatura + toplam_hakedis + toplam_gider

    # 2. CARİ BORÇ DURUMU
    
    # Yapılan Toplam Ödeme (Nakit + Çek + Havale)
    # Not: Çek verildiği an cari borçtan düşülmüş sayılır (Ödendi statüsüne bakılmaz).
    toplam_odenen = Odeme.objects.aggregate(
        t=Coalesce(Sum('tutar'), Decimal('0.00'))
    )['t']
    
    # Toplam Alacak (Faturalar + Hakedişler)
    cari_alacak_toplami = toplam_fatura + toplam_hakedis
    
    # Kalan Borç (Piyasa Borcu)
    kalan_cari_borc = cari_alacak_toplami - toplam_odenen

    # 3. YAKLAŞAN ÖDEMELER (ÇEKLER - 30 GÜN)
    # GÜNCELLEME: Sadece 'is_cek_odendi=False' olanları getiriyoruz.
    today = timezone.now().date()
    gelecek_30_gun = today + timezone.timedelta(days=30)
    
    yaklasan_cekler = Odeme.objects.filter(
        odeme_turu='cek',
        is_cek_odendi=False,  # ✅ EKLENDİ: Sadece ödenmemişleri getir
        vade_tarihi__gte=today,
        vade_tarihi__lte=gelecek_30_gun
    ).order_by('vade_tarihi')
    
    yaklasan_cek_toplam = yaklasan_cekler.aggregate(
        t=Coalesce(Sum('tutar'), Decimal('0.00'))
    )['t']

    # 4. EN BORÇLU 5 TEDARİKÇİ ANALİZİ
    tedarikciler = Tedarikci.objects.filter(is_active=True)
    borclu_listesi = []
    
    for ted in tedarikciler:
        # Borç (Fatura)
        t_fat = Fatura.objects.filter(tedarikci=ted).aggregate(
            t=Coalesce(Sum('genel_toplam'), Decimal('0.00'))
        )['t']
        
        # Borç (Hakediş)
        t_hak = Hakedis.objects.filter(satinalma__teklif__tedarikci=ted, onay_durumu=True).aggregate(
             t=Coalesce(Sum(F('brut_tutar') + F('kdv_tutari')), Decimal('0.00'))
        )['t']
        
        # Alacak (Ödeme)
        t_ode = Odeme.objects.filter(tedarikci=ted).aggregate(
            t=Coalesce(Sum('tutar'), Decimal('0.00'))
        )['t']
        
        bakiye = (t_fat + t_hak) - t_ode
        
        if bakiye > Decimal('1.00'):
            borclu_listesi.append({
                'isim': ted.firma_unvani,
                'bakiye': bakiye
            })
    
    borclu_listesi.sort(key=lambda x: x['bakiye'], reverse=True)
    top_5_borc = borclu_listesi[:5]

    # 5. DÖVİZ ÇEVİRİLERİ (BİLGİ AMAÇLI)
    if tcmb_kur_getir:
        kurlar = tcmb_kur_getir()
        usd_kur = Decimal(str(kurlar.get('USD', 35.50)))
        eur_kur = Decimal(str(kurlar.get('EUR', 38.20)))
        gbp_kur = Decimal(str(kurlar.get('GBP', 44.10)))
    else:
        usd_kur = Decimal('35.50')
        eur_kur = Decimal('38.20')
        gbp_kur = Decimal('44.10')

    def tl_to_fx(tl_val):
        val = Decimal(str(tl_val))
        return {
            'usd': val / usd_kur if usd_kur else 0,
            'eur': val / eur_kur if eur_kur else 0,
            'gbp': val / gbp_kur if gbp_kur else 0,
        }

    maliyet_doviz = tl_to_fx(fabrika_maliyeti)

    context = {
        'fabrika_maliyeti': fabrika_maliyeti,
        'maliyet_doviz': maliyet_doviz,
        
        'kalan_cari_borc': kalan_cari_borc,
        'toplam_gider': toplam_gider,
        
        'yaklasan_cek_toplam': yaklasan_cek_toplam,
        'yaklasan_cekler': yaklasan_cekler[:5],
        
        'top_5_borc': top_5_borc,
    }

    return render(request, 'finans_dashboard.html', context)

import logging
logger = logging.getLogger(__name__)

@login_required
def cari_ekstre(request, tedarikci_id):
    logger.error("### DEBUG cari_ekstre -> %s", __file__)
    tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
    hareketler = []
    guncel_kurlar = tcmb_kur_getir()

    # FATURALAR (TL borç)
    # FATURALAR (TL borç)  ✅ TEK KAYNAK: TEKLİF locked_total_try
    for fat in Fatura.objects.filter(tedarikci=tedarikci):
        tl_borc = None
        aciklama = f"Fatura #{fat.fatura_no}"

        # 1) Satınalma/teklif varsa: kilitli TL'yi kullan
        try:
            teklif = fat.satinalma.teklif if fat.satinalma_id else None
            if teklif:
                _net, _vat, gross = PaymentService.teklif_try_tutarlarini_getir(teklif)
                tl_borc = gross

                # Bilgi amaçlı: TL'den geriye doğru orj göster (çarpma yok)
                pb = (getattr(teklif, "para_birimi", None) or "TRY").upper().strip()
                if pb == "TL":
                    pb = "TRY"
                kur = to_decimal(getattr(teklif, "locked_rate", None) or getattr(teklif, "kur_degeri", None) or 0)

                if pb != "TRY" and kur and kur > 0:
                    orj_hint = (to_decimal(tl_borc) / to_decimal(kur)).quantize(Decimal("0.01"))
                    aciklama += (
                        f"<br><span class='badge bg-light text-dark border'>"
                        f"Bilgi: ~{orj_hint:,.2f} {pb} | Kur: {kur}</span>"
                    )
        except Exception:
            tl_borc = None

        # 2) Fallback (çok nadir): teklif yoksa, fatura genel toplamını TL kabul et
        if tl_borc is None:
            tl_borc = to_decimal(getattr(fat, "genel_toplam", 0)).quantize(Decimal("0.01"))

        hareketler.append({
            "tarih": fat.tarih,
            "aciklama": aciklama,
            "borc": tl_borc,
            "alacak": Decimal("0"),
            "tip": "fatura",
        })

    # HAKEDİŞLER (TL borç)  ✅ KUR YOK
    for hk in Hakedis.objects.filter(satinalma__teklif__tedarikci=tedarikci, onay_durumu=True):
        tl_borc = to_decimal(hk.odenecek_net_tutar).quantize(Decimal("0.01"))

        pb_info, kur_info = _teklif_currency_info_from_hk(hk, guncel_kurlar)
        aciklama = f"Hakediş #{hk.hakedis_no}"
        if pb_info != "TRY":
            try:
                orj_hint = (to_decimal(tl_borc) / to_decimal(kur_info)).quantize(Decimal("0.01")) if kur_info and kur_info > 0 else None
            except Exception:
                orj_hint = None
            if orj_hint is not None:
                aciklama += f"<br><span class='badge bg-light text-dark border'>Bilgi: ~{orj_hint:,.2f} {pb_info} | Kur: {kur_info}</span>"

        hareketler.append({
            "tarih": hk.tarih,
            "aciklama": aciklama,
            "borc": tl_borc,
            "alacak": Decimal("0"),
            "tip": "hakedis",
        })

    # ÖDEMELER (TL alacak)
    for o in Odeme.objects.filter(tedarikci=tedarikci):
        tl_alacak = to_decimal(o.tutar)
        aciklama = f"Ödeme ({o.get_odeme_turu_display()})"
        if o.aciklama:
            aciklama += f" - {o.aciklama}"

        if _odeme_dagitim_supported():
            try:
                if hasattr(o, "dagitimlar") and o.dagitimlar.exists():
                    aciklama += "<br><span class='badge bg-secondary'>Mahsup/Dağıtım var</span>"
            except Exception:
                pass

        hareketler.append({
            "tarih": o.tarih,
            "aciklama": aciklama,
            "borc": Decimal("0"),
            "alacak": tl_alacak,
            "tip": "odeme",
        })

    hareketler.sort(key=lambda x: x["tarih"])
    bakiye = Decimal("0.00")
    for h in hareketler:
        bakiye += (to_decimal(h["borc"]) - to_decimal(h["alacak"]))
        h["bakiye"] = bakiye

    return render(request, "cari_ekstre.html", {
        "tedarikci": tedarikci,
        "hareketler": hareketler,
        "son_bakiye": bakiye,
    })


@login_required
def odeme_dashboard(request):
    """
    Finansal İşlemler (Ödeme Merkezi)
    - Fatura kalanları: allocation + eski bağ
    - Hakediş kalanları: TL (kur uygulanmaz)
    - Cari listesi: Tedarikçi bazında
    - Yaklaşan çekler
    """
    if not yetki_kontrol(request.user, ["MUHASEBE_FINANS", "YONETICI"]):
        return redirect("erisim_engellendi")

    bugun = timezone.now().date()
    ufuk = bugun + timedelta(days=30)
    guncel_kurlar = tcmb_kur_getir()

    # 1) Ödenmemiş Hakediş Toplamı (TL)
    odenmemis_hakedis_toplam = Decimal("0.00")
    hakedisler = (
        Hakedis.objects
        .filter(onay_durumu=True)
        .select_related("satinalma__teklif__tedarikci")
    )
    for hk in hakedisler:
        odenmemis_hakedis_toplam += _hakedis_remaining_tl(hk)

    # 2) Ödenmemiş Fatura Toplamı (TL)
    odenmemis_fatura_toplam = Decimal("0.00")
    faturalar = Fatura.objects.select_related("tedarikci").all()
    for fat in faturalar:
        odenmemis_fatura_toplam += _invoice_remaining_tl(fat, guncel_kurlar)

    odenmemis_hakedis_toplam = to_decimal(odenmemis_hakedis_toplam).quantize(Decimal("0.01"))
    odenmemis_fatura_toplam = to_decimal(odenmemis_fatura_toplam).quantize(Decimal("0.01"))
    cari_borc_toplam = (odenmemis_fatura_toplam + odenmemis_hakedis_toplam).quantize(Decimal("0.01"))

    # 3) Cari Bakiye Listesi (Tedarikçi bazında)
    h_map = {}
    for hk in hakedisler:
        try:
            ted = hk.satinalma.teklif.tedarikci
        except Exception:
            continue
        kalan_tl = _hakedis_remaining_tl(hk)
        if kalan_tl > Decimal("0.00"):
            h_map[ted.id] = (h_map.get(ted.id, Decimal("0.00")) + kalan_tl).quantize(Decimal("0.01"))

    f_map = {}
    for fat in faturalar:
        ted = getattr(fat, "tedarikci", None)
        if not ted:
            continue
        kalan_tl = _invoice_remaining_tl(fat, guncel_kurlar)
        if kalan_tl > Decimal("0.00"):
            f_map[ted.id] = (f_map.get(ted.id, Decimal("0.00")) + kalan_tl).quantize(Decimal("0.01"))

    cari_listesi = []
    for ted in Tedarikci.objects.all().order_by("firma_unvani"):
        f_kalan = f_map.get(ted.id, Decimal("0.00"))
        h_kalan = h_map.get(ted.id, Decimal("0.00"))
        toplam = (f_kalan + h_kalan).quantize(Decimal("0.01"))
        if toplam > Decimal("0.00"):
            cari_listesi.append({
                "id": ted.id,
                "firma": ted.firma_unvani,
                "fatura_kalan": f_kalan,
                "hakedis_kalan": h_kalan,
                "toplam_kalan": toplam,
            })
    cari_listesi.sort(key=lambda x: x["toplam_kalan"], reverse=True)

    # 4) Yaklaşan Çekler
    yaklasan_cekler = (
        Odeme.objects
        .filter(odeme_turu="cek", vade_tarihi__isnull=False, vade_tarihi__gte=bugun, vade_tarihi__lte=ufuk)
        .select_related("tedarikci")
        .order_by("vade_tarihi", "id")
    )
    yaklasan_cek_toplam = yaklasan_cekler.aggregate(t=Sum("tutar"))["t"] or Decimal("0.00")

    return render(request, "odeme_dashboard.html", {
        "odenmemis_fatura_toplam": odenmemis_fatura_toplam,
        "odenmemis_hakedis_toplam": odenmemis_hakedis_toplam,
        "cari_borc_toplam": cari_borc_toplam,
        "cari_listesi": cari_listesi,
        "yaklasan_cekler": yaklasan_cekler,
        "yaklasan_cek_toplam": yaklasan_cek_toplam,
        "bugun": bugun,
        "ufuk": ufuk,
    })


@login_required
def cek_takibi(request):
    """
    ÇEK TAKİP MERKEZİ
    - Çekler vade tarihine göre ve ödenme durumuna göre kategorize edilir.
    """
    if not yetki_kontrol(request.user, ["MUHASEBE_FINANS", "YONETICI"]):
        return redirect("erisim_engellendi")

    bugun = timezone.now().date()
    otuz_gun_sonra = bugun + timedelta(days=30)

    # Sadece ÇEK olan ödemeleri çek
    cekler = Odeme.objects.filter(odeme_turu='cek').select_related('tedarikci').order_by('vade_tarihi')

    # 1. Gecikmişler: Vadesi bugünden küçük VE henüz ödenmemiş
    gecikmisler = cekler.filter(vade_tarihi__lt=bugun, is_cek_odendi=False)

    # 2. Yaklaşanlar: Bugün ile 30 gün arası VE henüz ödenmemiş
    yaklasanlar = cekler.filter(
        vade_tarihi__gte=bugun, 
        vade_tarihi__lte=otuz_gun_sonra, 
        is_cek_odendi=False
    )

    # 3. İleri Tarihliler: 30 günden sonrası VE henüz ödenmemiş
    ileri_tarihliler = cekler.filter(vade_tarihi__gt=otuz_gun_sonra, is_cek_odendi=False)

    # 4. Ödenmişler (Arşiv): is_cek_odendi=True olanlar
    odenmisler = cekler.filter(is_cek_odendi=True).order_by('-vade_tarihi')

    # Toplam Bekleyen Risk Hesabı (Gecikmiş + Yaklaşan + İleri)
    risk_qs = cekler.filter(is_cek_odendi=False)
    toplam_risk = sum([to_decimal(c.tutar) for c in risk_qs])

    context = {
        'gecikmisler': gecikmisler,
        'yaklasanlar': yaklasanlar,
        'ileri_tarihliler': ileri_tarihliler,
        'odenmisler': odenmisler,
        'toplam_risk': toplam_risk,
        'bugun': bugun,
    }

    return render(request, 'cek_takibi.html', context)

@login_required
def cek_durum_degistir(request, odeme_id):
    """
    Çekin durumunu 'Ödendi' <-> 'Bekliyor' arasında değiştirir.
    """
    if not yetki_kontrol(request.user, ["MUHASEBE_FINANS", "YONETICI"]):
        return redirect("erisim_engellendi")

    cek = get_object_or_404(Odeme, id=odeme_id, odeme_turu='cek')
    
    # Durumu tersine çevir (Toggle)
    eski_durum = cek.is_cek_odendi
    cek.is_cek_odendi = not eski_durum
    cek.save(update_fields=['is_cek_odendi'])
    
    if cek.is_cek_odendi:
        messages.success(request, f"✅ Çek 'ÖDENDİ' olarak işaretlendi. (Vade: {cek.vade_tarihi})")
    else:
        messages.warning(request, f"↩️ Çek tekrar 'BEKLİYOR' durumuna alındı.")

    return redirect('cek_takibi')


@login_required
def finans_ozeti(request):
    return redirect("finans_dashboard")


@login_required
def get_tedarikci_bakiye(request, tedarikci_id):
    """
    AJAX: seçilen tedarikçinin güncel kalan borcunu TL döndürür.
    (Fatura kalan TL + Hakediş kalan TL)
    """
    if not yetki_kontrol(request.user, ["MUHASEBE_FINANS", "YONETICI"]):
        return JsonResponse({"success": False, "message": "Yetkisiz"}, status=403)

    try:
        tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
        guncel_kurlar = tcmb_kur_getir()

        f_kalan = Decimal("0.00")
        for fat in Fatura.objects.filter(tedarikci=tedarikci):
            f_kalan += _invoice_remaining_tl(fat, guncel_kurlar)

        h_kalan = Decimal("0.00")
        for hk in Hakedis.objects.filter(satinalma__teklif__tedarikci=tedarikci, onay_durumu=True):
            h_kalan += _hakedis_remaining_tl(hk)

        toplam = (to_decimal(f_kalan) + to_decimal(h_kalan)).quantize(Decimal("0.01"))
        return JsonResponse({"success": True, "kalan_bakiye": float(toplam)})

    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)


@login_required
def odeme_sil(request, odeme_id):
    """
    ÖDEME SİLME
    - Allocation varsa önce dağıtımları siler, ilgili faturaları yeniden hesaplar.
    - Sonra ödemeyi siler.
    """
    if not yetki_kontrol(request.user, ["MUHASEBE_FINANS", "YONETICI"]):
        return redirect("erisim_engellendi")

    guncel_kurlar = tcmb_kur_getir()
    odeme = get_object_or_404(Odeme, id=odeme_id)

    try:
        with transaction.atomic():
            affected_faturas = []

            if _odeme_dagitim_supported():
                try:
                    affected_faturas = list(Fatura.objects.filter(dagitimlar__odeme=odeme).distinct())
                except Exception:
                    affected_faturas = []

                try:
                    OdemeDagitim.objects.filter(odeme=odeme).delete()
                except Exception:
                    pass

            if odeme.fatura:
                try:
                    if odeme.fatura not in affected_faturas:
                        affected_faturas.append(odeme.fatura)
                except Exception:
                    pass

            odeme.delete()

            for fat in affected_faturas:
                _recalc_invoice_odenen_tutar_orj(fat, guncel_kurlar)

        messages.warning(request, "🗑️ Ödeme kaydı silindi.")
    except Exception as e:
        messages.error(request, f"Silme hatası: {str(e)}")

    return redirect("odeme_dashboard")