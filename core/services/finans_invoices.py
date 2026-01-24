# core/services/finans_invoices.py
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import Depo, DepoHareket, FaturaKalem
from core.utils import to_decimal
from core.services.finans_payments import PaymentService


Q4 = Decimal("0.0001")


class InvoiceService:
    """
    Tek gerçek kural:
    - Fatura kayıtları TL total tutarları üzerinden ilerler.
    - Eğer kullanıcı KDV dahil fiyat girdiyse, kayıt sırasında KDV ayrıştırılır.
      (FaturaKalem.save zaten satır toplamlarını hesaplıyor.)
    - Bu servis, Siparişten otomatik fatura üretirken "matrah fiyat"ı güvenli üretir.
    """

    @staticmethod
    def _safe_divide_price_to_net(ham_fiyat: Decimal, kdv_orani: int) -> Decimal:
        """
        KDV dahil birim fiyatı, KDV hariç matraha çevirir (4 hane hassasiyet).
        """
        ham_fiyat = to_decimal(ham_fiyat, precision=4)
        if not kdv_orani or int(kdv_orani) <= 0:
            return ham_fiyat.quantize(Q4, rounding=ROUND_HALF_UP)

        katsayi = Decimal("1.0") + (Decimal(int(kdv_orani)) / Decimal("100.0"))
        if katsayi <= 0:
            return ham_fiyat.quantize(Q4, rounding=ROUND_HALF_UP)

        net = (ham_fiyat / katsayi).quantize(Q4, rounding=ROUND_HALF_UP)
        return net

    @staticmethod
    @transaction.atomic
    def fatura_olustur_siparisten(fatura, siparis):
        """
        SENARYO 1:
        Sipariş (SatinAlma) verilerini kullanarak faturayı ve kalemini OTOMATİK oluşturur.
        Kullanıcıdan kalem bilgisi beklemez.

        Güvenlik:
        - Teklif KDV dahil girildiyse net matraha çevirir.
        - Teklif döviz ise: onay anında kilitlenen TL mantığına dayanır.
          (Kilit alanlar varsa onları kullanır; yoksa fallback hesaplar.)
        """
        # 1) Fatura başlığı
        fatura.satinalma = siparis
        fatura.tedarikci = siparis.teklif.tedarikci
        fatura.save()

        teklif = siparis.teklif

        # 2) İşlem miktarı (sipariş miktarı)
        islem_miktari = to_decimal(siparis.toplam_miktar)

        malzeme = teklif.malzeme
        if not malzeme:
            # Hizmet/iş kalemi üzerinden fatura oluşturma senaryosu ileride eklenebilir.
            raise ValidationError("Siparişten otomatik fatura: Teklif üzerinde malzeme yok.")

        # 3) Teklif birim fiyatı (orijinal para birimi) -> TL mantığı
        ham_fiyat = to_decimal(teklif.birim_fiyat, precision=4)
        kdv_orani = int(getattr(teklif, "kdv_orani", 0) or 0)

        # Eğer teklif KDV dahil girildiyse önce net matrahı bul
        if bool(getattr(teklif, "kdv_dahil_mi", False)) and kdv_orani > 0:
            net_birim_orj = InvoiceService._safe_divide_price_to_net(ham_fiyat, kdv_orani)
        else:
            net_birim_orj = ham_fiyat.quantize(Q4, rounding=ROUND_HALF_UP)

        # 4) TL'ye çevirme: sadece teklif aşamasında / kilit mantığı
        # Bu noktada FaturaKalem.fiyat KDV hariç matrah olmalı ve TL olmalı.
        pb = (getattr(teklif, "para_birimi", None) or "TRY").upper().strip()
        kur = to_decimal(getattr(teklif, "kur_degeri", 1), precision=4)

        if pb and pb != "TRY":
            # Eğer teklif kilit TL alanları varsa, en güvenlisi: TL net toplamdan birim net üretmek
            # (Böylece "kur iki kere çarpıldı" riski sıfıra iner.)
            try:
                tl_net, _, _ = PaymentService.teklif_try_tutarlarini_getir(teklif)
                # tl_net = toplam net (KDV hariç) -> birime çevir
                if islem_miktari > 0:
                    birim_fiyat_tl = (to_decimal(tl_net) / to_decimal(islem_miktari)).quantize(Q4, rounding=ROUND_HALF_UP)
                else:
                    birim_fiyat_tl = (net_birim_orj * kur).quantize(Q4, rounding=ROUND_HALF_UP)
            except Exception:
                birim_fiyat_tl = (net_birim_orj * kur).quantize(Q4, rounding=ROUND_HALF_UP)
        else:
            birim_fiyat_tl = net_birim_orj.quantize(Q4, rounding=ROUND_HALF_UP)

        # 5) Kalem oluştur
        kalem = FaturaKalem.objects.create(
            fatura=fatura,
            malzeme=malzeme,
            miktar=islem_miktari,
            fiyat=birim_fiyat_tl,     # TL, KDV hariç matrah
            kdv_oran=kdv_orani,
            kdv_dahil_mi=False,       # fiyat artık net matrah olduğu için False
            aciklama=f"Siparişten otomatik: {siparis.id}",
        )

        # 6) Stok hareketi (varsayılan: sanal depo girişi)
        sanal_depo = Depo.objects.filter(is_sanal=True).first()
        if sanal_depo:
            DepoHareket.objects.create(
                ref_type="FATURA_KALEM",
                ref_id=kalem.id,
                ref_direction="IN",
                malzeme=malzeme,
                depo=sanal_depo,
                tarih=fatura.tarih or timezone.now().date(),
                islem_turu="giris",
                miktar=islem_miktari,
                tedarikci=fatura.tedarikci,
                aciklama=f"Fatura #{fatura.fatura_no} (Oto. Sipariş Girişi)",
            )

        # 7) Siparişi güncelle (faturalanan miktar)
        siparis.faturalanan_miktar = to_decimal(getattr(siparis, "faturalanan_miktar", 0)) + to_decimal(islem_miktari)
        siparis.save(update_fields=["faturalanan_miktar"])

        return fatura

    @staticmethod
    @transaction.atomic
    def fatura_kaydet_manuel(fatura, kalemler_formset, depo_id=None):
        """
        SENARYO 2:
        Serbest fatura. Kalemler formset'ten gelir.
        Stoklar seçilen depoya girer.

        Not:
        - FaturaKalem.save zaten KDV ayrıştırma + satır toplamlarını hesaplar.
        - Bu servis sadece "doğru depoya doğru stok hareketi" ve validasyon sağlar.
        """
        fatura.save()
        kalemler = kalemler_formset.save(commit=False)

        # Seçilen depo
        hedef_depo = Depo.objects.filter(id=depo_id).first() if depo_id else None

        # Depo seçilmediyse Sanal Depo varsayılan
        if not hedef_depo:
            hedef_depo = Depo.objects.filter(is_sanal=True).first()

        gercek_kalem_sayisi = 0
        for k in kalemler:
            if not k.malzeme_id or not k.miktar or to_decimal(k.miktar) <= 0:
                continue

            k.fatura = fatura
            k.save()
            gercek_kalem_sayisi += 1

            if hedef_depo:
                DepoHareket.objects.create(
                    ref_type="FATURA_KALEM",
                    ref_id=k.id,
                    ref_direction="IN",
                    malzeme=k.malzeme,
                    depo=hedef_depo,
                    tarih=fatura.tarih or timezone.now().date(),
                    islem_turu="giris",
                    miktar=to_decimal(k.miktar),
                    tedarikci=fatura.tedarikci,
                    aciklama=f"Serbest Fatura #{fatura.fatura_no}",
                )

        # Silinenleri temizle
        for obj in kalemler_formset.deleted_objects:
            obj.delete()

        if gercek_kalem_sayisi == 0:
            raise ValidationError("En az 1 geçerli satır girmelisiniz.")

        return fatura