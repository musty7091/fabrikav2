# core/signals.py
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction

from .models import DepoTransfer, SatinAlma
from core.services import StockService

logger = logging.getLogger(__name__)

@receiver(post_save, sender=DepoTransfer)
def depo_transfer_post_save(sender, instance, created, **kwargs):
    """
    Uzman Önerisi:
    - FIFO ile otomatik sipariş eşleştirme yapar.
    - Stok hareketlerini merkezi StockService üzerinden yönetir.
    - Tüm işlemi transaction.atomic ile garantiye alır.
    """
    if not created:
        return

    with transaction.atomic():
        # 1) Sipariş (bagli_siparis) belirleme ve FIFO Eşleşme
        siparis_obj = getattr(instance, "bagli_siparis", None)

        if not siparis_obj and instance.kaynak_depo.is_sanal:
            try:
                aday_siparisler = (
                    SatinAlma.objects
                    .filter(teklif__malzeme=instance.malzeme)
                    .exclude(teslimat_durumu="tamamlandi")
                    .order_by("created_at")
                )

                for aday in aday_siparisler:
                    # 'sanal_depoda_bekleyen' üzerinden FIFO kontrolü
                    if aday.sanal_depoda_bekleyen > 0:
                        siparis_obj = aday
                        
                        # Açıklamayı ve siparişi güncelle
                        mevcut_not = (instance.aciklama or "").strip()
                        ek_not = f"Oto. Sipariş #{aday.id}"
                        instance.aciklama = f"{mevcut_not} ({ek_not})" if mevcut_not else ek_not
                        instance.bagli_siparis = aday
                        
                        # Sadece gerekli alanları update et (recursive sinyali önlemek için)
                        instance.save(update_fields=["bagli_siparis", "aciklama"])
                        break

            except Exception:
                logger.exception("FIFO eşleşme hatası (DepoTransfer id=%s)", instance.id)

        # 2) STOK DEĞİŞTİREN TEK KAPI: StockService
        StockService.execute_transfer(
            malzeme=instance.malzeme,
            miktar=instance.miktar,
            kaynak_depo=instance.kaynak_depo,
            hedef_depo=instance.hedef_depo,
            siparis=siparis_obj,
            aciklama=f"Transfer #{instance.id} | {instance.aciklama or ''}",
            tarih=instance.tarih,
        )

        # 3) Sipariş durum güncellemesini tetikle
        if siparis_obj:
            siparis_obj.save()