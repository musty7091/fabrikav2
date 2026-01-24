from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from core.models import Hakedis
from core.utils import to_decimal, tcmb_kur_getir


Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")


def q2(x: Decimal) -> Decimal:
    return to_decimal(x).quantize(Q2, rounding=ROUND_HALF_UP)


def q4(x: Decimal) -> Decimal:
    return to_decimal(x, precision=4).quantize(Q4, rounding=ROUND_HALF_UP)


class PaymentService:
    """
    Tek gerçek kural:
    - Döviz sadece TEKLİF aşamasında olabilir.
    - Onay anında kur kilitlenir ve TL tutarlar "tek kaynak" olarak saklanır.
    - Hakediş/Finans ekranları KDV/kur hesaplamaz; sadece saklı TL toplamları okur.

    Bu servis:
    - Mevcut projeyi kırmadan çalışır.
    - Teklif üzerinde locked_* alanları varsa onları doldurur.
    - locked_* alanları yoksa (eski sistem) fallback hesaplar.
    """

    # ---------------------------------------------------------------------
    # 1) Hakediş validasyonları
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # 2) KDV hesaplaması (teklif/fatura satırı)
    # ---------------------------------------------------------------------
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

        # -1 (KDV muaf) gibi değerleri 0 kabul ediyoruz
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

    # ---------------------------------------------------------------------
    # 3) Teklif -> Kur bulma
    # ---------------------------------------------------------------------
    @staticmethod
    def _resolve_fx_rate_for_teklif(teklif, for_date=None) -> Tuple[str, Decimal, str]:
        """
        Teklif için kullanılacak kuru belirler.
        Öncelik:
          1) teklif.kur_degeri (kullanıcı girmiş olabilir)
          2) tcmb_kur_getir() (today.xml; hafta sonu genelde son iş gününü döndürür)

        Dönüş: (para_birimi, kur, kaynak)
        """
        pb = (getattr(teklif, "para_birimi", None) or "TRY").upper().strip()
        if pb in ("TL", "", None):
            pb = "TRY"

        # TRY ise 1
        if pb == "TRY":
            return "TRY", Decimal("1.0000"), "TRY"

        # 1) teklif.kur_degeri
        kur = to_decimal(getattr(teklif, "kur_degeri", None) or 0, precision=4)
        if kur and kur > 0:
            return pb, kur.quantize(Q4, rounding=ROUND_HALF_UP), "Manual/Existing"

        # 2) TCMB today.xml (fallback)
        kurlar = tcmb_kur_getir()
        kur2 = to_decimal(kurlar.get(pb, 0) or 0, precision=4)
        if kur2 and kur2 > 0:
            return pb, kur2.quantize(Q4, rounding=ROUND_HALF_UP), "TCMB"

        raise ValidationError(
            f"{pb} için kur bulunamadı. (Kur değeri girin veya TCMB bağlantısını kontrol edin.)"
        )

    # ---------------------------------------------------------------------
    # 4) Onay anında TL Kilitleme (locked_* alanları)
    # ---------------------------------------------------------------------
    @staticmethod
    def teklif_onayinda_tl_sabitle(teklif, approval_datetime=None, force: bool = False) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Teklifi TL'ye SABİTLER (kilitler).
        - Onay anında bir kere çalıştırılmalıdır.
        - Teklif modelinde locked_* alanları varsa doldurur.

        Dönen: (net_try, vat_try, gross_try)
        """
        if approval_datetime is None:
            approval_datetime = timezone.now()

        # Zaten kilitliyse ve force değilse dokunma
        if not force and hasattr(teklif, "locked_total_try"):
            try:
                existing = to_decimal(getattr(teklif, "locked_total_try", 0))
                if existing and existing > 0:
                    net = to_decimal(getattr(teklif, "locked_subtotal_try", 0))
                    vat = to_decimal(getattr(teklif, "locked_vat_try", 0))
                    gross = to_decimal(getattr(teklif, "locked_total_try", 0))
                    return q2(net), q2(vat), q2(gross)
            except Exception:
                pass

        # Orijinal (teklif para birimi) tutarları
        miktar = to_decimal(getattr(teklif, "miktar", 0))
        birim_fiyat = to_decimal(getattr(teklif, "birim_fiyat", 0))

        kdv_orani = getattr(teklif, "kdv_orani", 0)
        if kdv_orani == -1:
            kdv_orani = 0

        kdv_dahil_mi = bool(getattr(teklif, "kdv_dahil_mi", False))

        net_orj, vat_orj, gross_orj = PaymentService.teklif_tutarlarini_hesapla(
            miktar=miktar,
            birim_fiyat=birim_fiyat,
            kdv_orani=kdv_orani,
            kdv_dahil_mi=kdv_dahil_mi,
        )

        pb, kur, kaynak = PaymentService._resolve_fx_rate_for_teklif(
            teklif, for_date=approval_datetime.date()
        )

        # TL'ye çevir (tek sefer)
        net_try = q2(net_orj * kur)
        vat_try = q2(vat_orj * kur)
        gross_try = q2(gross_orj * kur)

        update_fields = []

        # Kur bilgisini de kilit mantığıyla senkron tutalım
        if hasattr(teklif, "kur_degeri"):
            teklif.kur_degeri = q4(kur)
            update_fields.append("kur_degeri")

        if hasattr(teklif, "para_birimi"):
            teklif.para_birimi = pb
            update_fields.append("para_birimi")

        # locked_* alanları (senin models.py’de mevcut) :contentReference[oaicite:1]{index=1}
        if hasattr(teklif, "locked_at"):
            teklif.locked_at = approval_datetime
            update_fields.append("locked_at")

        if hasattr(teklif, "locked_rate"):
            # model decimal_places=6; biz 4 precision’dan geleni 6’ya uyacak şekilde yazarız
            teklif.locked_rate = to_decimal(kur, precision=6)
            update_fields.append("locked_rate")

        if hasattr(teklif, "locked_rate_date"):
            teklif.locked_rate_date = approval_datetime.date()
            update_fields.append("locked_rate_date")

        if hasattr(teklif, "locked_rate_source"):
            teklif.locked_rate_source = kaynak
            update_fields.append("locked_rate_source")

        if hasattr(teklif, "locked_subtotal_try"):
            teklif.locked_subtotal_try = net_try
            update_fields.append("locked_subtotal_try")

        if hasattr(teklif, "locked_vat_try"):
            teklif.locked_vat_try = vat_try
            update_fields.append("locked_vat_try")

        if hasattr(teklif, "locked_total_try"):
            teklif.locked_total_try = gross_try
            update_fields.append("locked_total_try")

        if update_fields:
            teklif.save(update_fields=list(dict.fromkeys(update_fields)))

        return net_try, vat_try, gross_try

    @staticmethod
    def teklif_try_tutarlarini_getir(teklif) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Öncelik: locked_* alanları varsa onları döndür.
        Yoksa (geriye uyum) anlık hesapla.
        """
        if hasattr(teklif, "locked_total_try"):
            try:
                gross = to_decimal(getattr(teklif, "locked_total_try", 0))
                if gross and gross > 0:
                    net = to_decimal(getattr(teklif, "locked_subtotal_try", 0))
                    vat = to_decimal(getattr(teklif, "locked_vat_try", 0))
                    return q2(net), q2(vat), q2(gross)
            except Exception:
                pass

        # fallback: anlık hesap (eski sistem)
        pb, kur, _kaynak = PaymentService._resolve_fx_rate_for_teklif(
            teklif, for_date=timezone.now().date()
        )

        miktar = to_decimal(getattr(teklif, "miktar", 0))
        birim_fiyat = to_decimal(getattr(teklif, "birim_fiyat", 0))

        kdv_orani = getattr(teklif, "kdv_orani", 0)
        if kdv_orani == -1:
            kdv_orani = 0

        kdv_dahil_mi = bool(getattr(teklif, "kdv_dahil_mi", False))

        net_orj, vat_orj, gross_orj = PaymentService.teklif_tutarlarini_hesapla(
            miktar=miktar,
            birim_fiyat=birim_fiyat,
            kdv_orani=kdv_orani,
            kdv_dahil_mi=kdv_dahil_mi,
        )

        return q2(net_orj * kur), q2(vat_orj * kur), q2(gross_orj * kur)