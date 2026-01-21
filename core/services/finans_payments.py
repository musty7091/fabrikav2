# core/services/finans_payments.py
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Sum
from core.models import Hakedis, SatinAlma
from core.utils import to_decimal 

class PaymentService:
    @staticmethod
    def hakedis_validasyon(siparis_id, yeni_oran):
        """
        Hakediş oranının %100'ü geçip geçmediğini kontrol eder.
        """
        mevcut_toplam = Hakedis.objects.filter(satinalma_id=siparis_id).aggregate(
            t=Sum('tamamlanma_orani')
        )['t'] or Decimal('0.00')

        toplam_hedeflenen = to_decimal(mevcut_toplam) + to_decimal(yeni_oran)
        
        if toplam_hedeflenen > Decimal('100.00'):
            kalan = Decimal('100.00') - to_decimal(mevcut_toplam)
            raise ValidationError(f"Toplam ilerleme %100'ü geçemez! Kalan kapasite: %{kalan}")
        
        return True

    @staticmethod
    def siparis_guncelle(siparis, hakedis_orani):
        """
        Hakediş onaylandığında siparişin ilerleme durumunu günceller.
        """
        try:
            toplam_is = to_decimal(siparis.toplam_miktar)
            yapilan_miktar = (toplam_is * to_decimal(hakedis_orani)) / Decimal('100.00')
            
            siparis.teslim_edilen = to_decimal(siparis.teslim_edilen) + yapilan_miktar
            siparis.faturalanan_miktar = to_decimal(siparis.faturalanan_miktar) + yapilan_miktar
            siparis.save()
        except Exception:
            pass