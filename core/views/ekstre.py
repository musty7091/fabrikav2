# core/views/ekstre.py
from decimal import Decimal
from django.shortcuts import render
from django.db.models import Sum, Q

from core.models import (
    Malzeme, Depo, DepoHareket,
    Tedarikci, Fatura, Odeme, Hakedis
)

def stok_ekstresi(request):
    malzeme_id = request.GET.get("malzeme")
    depo_id = request.GET.get("depo")
    tur = request.GET.get("tur")          # giris/cikis/iade
    ref_type = request.GET.get("ref_type") # TRANSFER/FATURA/MANUEL/IADE
    d1 = request.GET.get("d1")
    d2 = request.GET.get("d2")

    qs = DepoHareket.objects.select_related("malzeme", "depo").all().order_by("-tarih", "-id")

    if malzeme_id:
        qs = qs.filter(malzeme_id=malzeme_id)
    if depo_id:
        qs = qs.filter(depo_id=depo_id)
    if tur:
        qs = qs.filter(islem_turu=tur)
    if ref_type:
        qs = qs.filter(ref_type=ref_type)
    if d1:
        qs = qs.filter(tarih__gte=d1)
    if d2:
        qs = qs.filter(tarih__lte=d2)

    ozet = qs.aggregate(
        toplam_giris=Sum("miktar", filter=Q(islem_turu="giris")),
        toplam_cikis=Sum("miktar", filter=Q(islem_turu="cikis")),
        toplam_iade=Sum("miktar", filter=Q(islem_turu="iade")),
    )
    ozet = {k: (v or Decimal("0")) for k, v in ozet.items()}
    ozet["net"] = ozet["toplam_giris"] - ozet["toplam_cikis"] - ozet["toplam_iade"]

    return render(request, "core/ekstre_stok.html", {
        "malzemeler": Malzeme.objects.all().order_by("isim"),
        "depolar": Depo.objects.all().order_by("isim"),
        "hareketler": qs[:500],
        "ozet": ozet,
    })


def cari_ekstresi(request):
    tedarikci_id = request.GET.get("tedarikci")
    d1 = request.GET.get("d1")
    d2 = request.GET.get("d2")

    finans_satirlar = []
    stok_hareketleri = DepoHareket.objects.none()

    # tedarikci_id güvenli dönüşüm (tek yerde)
    try:
        tedarikci_id = int(tedarikci_id) if tedarikci_id else None
    except (TypeError, ValueError):
        tedarikci_id = None

    if tedarikci_id:
        faturalar = (
            Fatura.objects
            .select_related("satinalma", "satinalma__teklif", "satinalma__teklif__tedarikci")
            .filter(satinalma__teklif__tedarikci_id=tedarikci_id)
        )

        odemeler = Odeme.objects.filter(tedarikci_id=tedarikci_id)

        hakedisler = (
            Hakedis.objects
            .select_related("satinalma", "satinalma__teklif", "satinalma__teklif__tedarikci")
            .filter(satinalma__teklif__tedarikci_id=tedarikci_id)
        )

        if d1:
            faturalar = faturalar.filter(tarih__gte=d1)
            odemeler = odemeler.filter(tarih__gte=d1)
            hakedisler = hakedisler.filter(tarih__gte=d1)
        if d2:
            faturalar = faturalar.filter(tarih__lte=d2)
            odemeler = odemeler.filter(tarih__lte=d2)
            hakedisler = hakedisler.filter(tarih__lte=d2)

        for f in faturalar:
            finans_satirlar.append({"tarih": f.tarih, "tip": "FATURA", "borc": f.tutar, "alacak": Decimal("0"), "aciklama": f"Fatura {f.fatura_no}"})
        for o in odemeler:
            finans_satirlar.append({"tarih": o.tarih, "tip": "ÖDEME", "borc": Decimal("0"), "alacak": o.tutar, "aciklama": o.aciklama or ""})
        for h in hakedisler:
            finans_satirlar.append({"tarih": h.tarih, "tip": "HAKEDİŞ", "borc": h.odenecek_net_tutar, "alacak": Decimal("0"), "aciklama": f"Hakediş #{h.hakedis_no}"})

        finans_satirlar.sort(key=lambda x: (x["tarih"], x["tip"]))

        bakiye = Decimal("0")
        for s in finans_satirlar:
            bakiye += (s["borc"] - s["alacak"])
            s["bakiye"] = bakiye

        stok_hareketleri = (
            DepoHareket.objects
            .select_related("malzeme", "depo", "siparis", "siparis__teklif", "siparis__teklif__tedarikci")
            .filter(
                Q(tedarikci_id=tedarikci_id) |
                Q(siparis__teklif__tedarikci_id=tedarikci_id)
            )
            .order_by("-tarih", "-id")
        )

        # ✅ stok tarafına da tarih filtresi
        if d1:
            stok_hareketleri = stok_hareketleri.filter(tarih__gte=d1)
        if d2:
            stok_hareketleri = stok_hareketleri.filter(tarih__lte=d2)

    return render(request, "core/ekstre_cari.html", {
        "tedarikciler": Tedarikci.objects.all().order_by("firma_unvani"),
        "finans_satirlar": finans_satirlar,
        "stok_hareketleri": stok_hareketleri[:500],
    })