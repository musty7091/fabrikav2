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
            pb, kur = get_smart_exchange_rate(fat, guncel_kurlar)

            genel_toplam = to_decimal(getattr(fat, "genel_toplam", 0))
            kur = to_decimal(kur) if kur else Decimal("1.0")

            # 🔴 KRİTİK: Para birimi bulunamadıysa (pb TRY döner) ama fatura aslında döviz olabilir.
            # Bu durumda sadece "faturaya bağlı" ödemelerden kur türetiyoruz.
            # (Yanlış eşleştirme riskini azaltmak için tedarikçi toplamından değil, faturaya bağlı olandan bakıyoruz.)
            if pb == "TRY":
                odenen_tl = (
                    Odeme.objects.filter(fatura=fat)
                    .aggregate(toplam=Sum("tutar"))["toplam"]
                    or Decimal("0")
                )
                odenen_tl = to_decimal(odenen_tl)

                # genel_toplam 0 ise bölme yapma
                if genel_toplam > Decimal("0.0001"):
                    # Ödeme, fatura tutarından bariz büyükse bu fatura dövizdir → kur türet
                    if odenen_tl > genel_toplam * Decimal("1.50"):
                        kur = odenen_tl / genel_toplam
                        pb = "USD"  # para birimi tespit edilemiyorsa en azından döviz olduğunu belirtelim

            tl_borc = genel_toplam * kur

            aciklama = f"Fatura: {fat.aciklama or ''}".strip()

            # Döviz bilgisi badge
            if pb != "TRY":
                aciklama += (
                    f"<br><span class='badge bg-light text-dark border'>"
                    f"Orj: {genel_toplam:,.2f} {pb} | Kur: {kur}</span>"
                )

            hareketler.append(
                {
                    "tarih": fat.tarih,
                    "aciklama": aciklama,
                    "borc": tl_borc,
                    "alacak": Decimal("0"),
                    "tip": "Fatura",
                }
            )

        # --------------------
        # 2) HAKEDİŞLER (TL'ye çevrilmiş borç)
        # --------------------
        for hk in hakedisler:
            pb, kur = get_smart_exchange_rate(hk, guncel_kurlar)
            pb = "TRY" if pb in ["TL", "TRY"] else pb
            kur = to_decimal(kur) if kur else Decimal("1.0")

            hk_tutar = to_decimal(getattr(hk, "odenecek_net_tutar", 0))
            tl_borc = hk_tutar * kur

            is_adi = "İşçilik"
            try:
                if hk.satinalma and hk.satinalma.teklif and hk.satinalma.teklif.is_kalemi:
                    is_adi = hk.satinalma.teklif.is_kalemi.isim
            except Exception:
                pass

            aciklama = f"Hakediş ({is_adi})"
            if pb != "TRY":
                aciklama += (
                    f"<br><span class='badge bg-light text-dark border'>"
                    f"Orj: {hk_tutar:,.2f} {pb} | Kur: {kur}</span>"
                )

            hareketler.append(
                {
                    "tarih": hk.tarih,
                    "aciklama": aciklama,
                    "borc": tl_borc,
                    "alacak": Decimal("0"),
                    "tip": "Hakediş",
                }
            )

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
