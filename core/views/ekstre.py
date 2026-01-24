from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from decimal import Decimal
from core.models import Tedarikci, Fatura, Hakedis, Odeme, Malzeme, DepoHareket
from core.utils import to_decimal, tcmb_kur_getir

# ⚠️ Döviz/kur mantığı zaten sende finans_payments.py içinde var
# Bu dosyadan import ederek aynı mantığı kullanıyoruz.
from core.views.finans_payments import get_smart_exchange_rate


@login_required
def cari_ekstresi(request):
    """
    Tedarikçi Cari Ekstresi (TL)
    - Dövizli faturaları doğru kur ile TL'ye çevirir.
    - Faturanın para birimi/kur bilgisi yoksa, faturaya bağlı TL ödemelerden kur türetir (güvenli koşullarda).
    - Template uyumu: son_bakiye gönderir.
    """
    tedarikciler = Tedarikci.objects.all().order_by("firma_unvani")
    secilen_tedarikci = None
    hareketler = []

    tedarikci_id = request.GET.get("tedarikci")
    tarih1 = request.GET.get("d1")
    tarih2 = request.GET.get("d2")

    guncel_kurlar = tcmb_kur_getir()

    if tedarikci_id:
        secilen_tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)

        faturalar = Fatura.objects.filter(tedarikci=secilen_tedarikci)
        hakedisler = Hakedis.objects.filter(
            satinalma__teklif__tedarikci=secilen_tedarikci, onay_durumu=True
        )
        odemeler = Odeme.objects.filter(tedarikci=secilen_tedarikci)

        # Tarih Filtresi
        if tarih1:
            faturalar = faturalar.filter(tarih__gte=tarih1)
            hakedisler = hakedisler.filter(tarih__gte=tarih1)
            odemeler = odemeler.filter(tarih__gte=tarih1)
        if tarih2:
            faturalar = faturalar.filter(tarih__lte=tarih2)
            hakedisler = hakedisler.filter(tarih__lte=tarih2)
            odemeler = odemeler.filter(tarih__lte=tarih2)

        faturalar = faturalar.order_by("tarih", "id")

        # --------------------
        # 1) FATURALAR (TL'ye çevrilmiş borç)
        # --------------------
        for fat in faturalar:
            # ✅ KRİTİK: Fatura.genel_toplam zaten TL tutulur => ASLA kur uygulanmaz
            tl_borc = to_decimal(getattr(fat, "genel_toplam", 0)).quantize(Decimal("0.01"))

            aciklama = f"Fatura: {fat.aciklama or ''}".strip()

            # Bilgi amaçlı: bağlı teklif dövizliyse TL'den geriye doğru "orj" göster (TL / kur)
            try:
                teklif = fat.satinalma.teklif if getattr(fat, "satinalma_id", None) else None
                if teklif:
                    pb = (getattr(teklif, "para_birimi", "TRY") or "TRY").upper().strip()
                    if pb in ("TL", "", None):
                        pb = "TRY"

                    # öncelik: locked_rate, sonra kur_degeri
                    kur = to_decimal(
                        getattr(teklif, "locked_rate", None) or getattr(teklif, "kur_degeri", None) or 0,
                        precision=6
                    )

                    if pb != "TRY" and kur and kur > 0:
                        orj_hint = (to_decimal(tl_borc) / to_decimal(kur)).quantize(Decimal("0.01"))
                        aciklama += (
                            f"<br><span class='badge bg-light text-dark border'>"
                            f"Orj: {orj_hint:,.2f} {pb} | Kur: {kur}</span>"
                        )
            except Exception:
                pass

            hareketler.append(
                {
                    "tarih": fat.tarih,
                    "aciklama": aciklama,
                    "borc": tl_borc,          # ✅ TL
                    "alacak": Decimal("0"),
                    "tip": "Fatura",
                }
            )

        # --------------------
        # 2) HAKEDİŞLER (TL'ye çevrilmiş borç)
        # --------------------
        # HAKEDİŞLER (TL borç) - KRİTİK: Hakediş TL tutulur => ASLA kur uygulanmaz
        for hk in hakedisler:
            hk_tutar = to_decimal(getattr(hk, "odenecek_net_tutar", 0)).quantize(Decimal("0.01"))
            tl_borc = hk_tutar  # ✅ TL

            aciklama = f"Hakediş: {getattr(hk, 'aciklama', '') or ''}".strip()

            # Bilgi amaçlı: teklif dövizliyse TL'den orj'a geri hesap (TL / kur)
            try:
                teklif = hk.satinalma.teklif if getattr(hk, "satinalma_id", None) else None
                if teklif:
                    pb = (getattr(teklif, "para_birimi", "TRY") or "TRY").upper().strip()
                    if pb in ("TL", "", None):
                        pb = "TRY"

                    kur = to_decimal(
                        getattr(teklif, "locked_rate", None) or getattr(teklif, "kur_degeri", None) or 0,
                        precision=6
                    )

                    if pb != "TRY" and kur and kur > 0:
                        orj_hint = (to_decimal(tl_borc) / to_decimal(kur)).quantize(Decimal("0.01"))
                        aciklama += (
                            f"<br><span class='badge bg-light text-dark border'>"
                            f"Orj: {orj_hint:,.2f} {pb} | Kur: {kur}</span>"
                        )
            except Exception:
                pass

            hareketler.append({
                "tarih": hk.tarih,
                "aciklama": aciklama,
                "borc": tl_borc,            # ✅ TL
                "alacak": Decimal("0"),
                "tip": "Hakedis",
            })

        # --------------------
        # 3) ÖDEMELER (TL alacak)
        # --------------------
        for odeme in odemeler:
            hareketler.append(
                {
                    "tarih": odeme.tarih,
                    "aciklama": f"Ödeme: {odeme.get_odeme_turu_display()}",
                    "borc": Decimal("0"),
                    "alacak": to_decimal(getattr(odeme, "tutar", 0)),
                    "tip": "Ödeme",
                }
            )

        # --------------------
        # 4) Sırala & Bakiye Hesapla
        # --------------------
        hareketler.sort(key=lambda x: x["tarih"])

        bakiye = Decimal("0.00")
        for h in hareketler:
            h["borc"] = to_decimal(h.get("borc", 0))
            h["alacak"] = to_decimal(h.get("alacak", 0))
            bakiye += (h["borc"] - h["alacak"])
            h["bakiye"] = bakiye

        son_bakiye = bakiye
    else:
        son_bakiye = Decimal("0.00")

    context = {
        "tedarikciler": tedarikciler,
        "secilen_tedarikci": secilen_tedarikci,
        "hareketler": hareketler,
        "son_bakiye": son_bakiye,
        "filtre_d1": tarih1,
        "filtre_d2": tarih2,
    }

    return render(request, "cari_ekstre.html", context)


@login_required
def stok_ekstresi(request):
    """
    Malzeme Stok Ekstresi
    Düzeltme: Modeldeki 'depo_tipi' alanına göre kontrol yapıldı.
    """
    malzemeler = Malzeme.objects.all()
    secilen_malzeme = None
    hareketler = []

    malzeme_id = request.GET.get("malzeme")
    if malzeme_id:
        secilen_malzeme = get_object_or_404(Malzeme, id=malzeme_id)

        depo_hareketleri = DepoHareket.objects.filter(malzeme=secilen_malzeme).order_by(
            "tarih", "id"
        )

        stok_bakiye = Decimal("0")

        for dh in depo_hareketleri:
            miktar = to_decimal(dh.miktar)
            giris = Decimal("0")
            cikis = Decimal("0")

            if dh.islem_turu == "giris":
                giris = miktar

                if dh.depo and dh.depo.depo_tipi == "CONSUMPTION":
                    pass
                else:
                    stok_bakiye += miktar

            elif dh.islem_turu in ["cikis", "transfer", "iade"]:
                cikis = miktar
                stok_bakiye -= miktar

            islem_adi = (
                dh.get_islem_turu_display()
                if hasattr(dh, "get_islem_turu_display")
                else dh.islem_turu
            )

            hareketler.append(
                {
                    "tarih": dh.tarih,
                    "islem": islem_adi,
                    "aciklama": dh.aciklama,
                    "giris": giris,
                    "cikis": cikis,
                    "bakiye": stok_bakiye,
                    "depo": dh.depo.isim if dh.depo else "-",
                    "depo_tipi": dh.depo.get_depo_tipi_display() if dh.depo else "",
                }
            )

    return render(
        request,
        "stok_ekstresi.html",
        {"malzemeler": malzemeler, "secilen_malzeme": secilen_malzeme, "hareketler": hareketler},
    )
