from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db.models import Sum

from core.models import Hakedis
from core.utils import to_decimal


class PaymentService:
    @staticmethod
    def hakedis_validasyon(siparis_id, yeni_oran):
        """
        Hakediş oranlarının toplamı %100'ü geçmesin.
        """
        mevcut_toplam = (
            Hakedis.objects.filter(satinalma_id=siparis_id)
            .aggregate(t=Sum("tamamlanma_orani"))["t"]
            or Decimal("0.00")
        )

        toplam_hedeflenen = to_decimal(mevcut_toplam) + to_decimal(yeni_oran)

        if toplam_hedeflenen > Decimal("100.00"):
            kalan = (Decimal("100.00") - to_decimal(mevcut_toplam)).quantize(Decimal("0.01"))
            raise ValidationError(f"Toplam ilerleme %100'ü geçemez! Kalan kapasite: %{kalan}")

        return True

    @staticmethod
    def siparis_guncelle(siparis, hakedis_orani):
        """
        Hakediş onaylandığında siparişin ilerleme durumunu günceller.
        (Miktar bazlı: teslim_edilen ve faturalanan_miktar artar)
        """
        toplam_is = to_decimal(getattr(siparis, "toplam_miktar", 0))
        oran = to_decimal(hakedis_orani)

        if toplam_is <= 0 or oran <= 0:
            return

        yapilan_miktar = (toplam_is * oran / Decimal("100.00")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        siparis.teslim_edilen = to_decimal(getattr(siparis, "teslim_edilen", 0)) + yapilan_miktar
        siparis.faturalanan_miktar = to_decimal(getattr(siparis, "faturalanan_miktar", 0)) + yapilan_miktar
        siparis.save(update_fields=["teslim_edilen", "faturalanan_miktar"])

    @staticmethod
    def teklif_tutarlarini_hesapla(miktar, birim_fiyat, kdv_orani, kdv_dahil_mi: bool):
        """
        Tekliften tutar hesaplar.

        Kural:
        - kdv_dahil_mi=True ise: birim_fiyat KDV DAHİL kabul edilir.
          toplam_kdv_dahil = miktar * birim_fiyat
          tutar_kdv_haric = toplam / (1 + kdv_orani/100)
          kdv = toplam - tutar

        - kdv_dahil_mi=False ise: birim_fiyat KDV HARİÇ kabul edilir.
          tutar_kdv_haric = miktar * birim_fiyat
          kdv = tutar * (kdv_orani/100)
          toplam_kdv_dahil = tutar + kdv

        Dönüş: (tutar_kdv_haric, kdv_tutar, toplam_kdv_dahil)
        """
        miktar = to_decimal(miktar)
        birim_fiyat = to_decimal(birim_fiyat)
        kdv_orani = to_decimal(kdv_orani)

        if miktar < 0:
            miktar = Decimal("0.00")
        if birim_fiyat < 0:
            birim_fiyat = Decimal("0.00")

        # -1 (KDV muaf) gibi değerleri 0 kabul ediyoruz (finans ekranı için)
        if kdv_orani < 0:
            kdv_orani = Decimal("0.00")

        oran = (kdv_orani / Decimal("100.00"))

        if kdv_dahil_mi:
            toplam = (miktar * birim_fiyat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            bolen = (Decimal("1.00") + oran)
            if bolen <= 0:
                tutar = toplam
            else:
                tutar = (toplam / bolen).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            kdv = (toplam - tutar).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return tutar, kdv, toplam

        tutar = (miktar * birim_fiyat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        kdv = (tutar * oran).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        toplam = (tutar + kdv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return tutar, kdv, toplam
