# core/signals.py
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction

from .models import DepoTransfer, SatinAlma
from core.services import StockService

logger = logging.getLogger(__name__)


@receiver(post_save, sender=DepoTransfer)
def depo_transfer_post_save(sender, instance: DepoTransfer, created: bool, **kwargs):
    """
    Hedef:
    - DepoTransfer sadece "belge"dir.
    - Stok hareketini TEK KAPI StockService yazar.
    - FIFO eşleştirme sadece Vendor kaynaklı çıkışlarda çalışır.
    - Idempotency: transfer_id ile çift kayıt olmaz.
    """
    if not created:
        return

    with transaction.atomic():
        siparis_obj = instance.bagli_siparis

        # 1) FIFO eşleştirme (sadece Vendor'dan çıkışlarda)
        try:
            kaynak_vendor = (
                getattr(instance.kaynak_depo, "depo_tipi", None) == "VENDOR"
                or getattr(instance.kaynak_depo, "is_sanal", False)
            )

            if (siparis_obj is None) and kaynak_vendor:
                adaylar = (
                    SatinAlma.objects
                    .filter(teklif__malzeme=instance.malzeme)
                    .exclude(teslimat_durumu="tamamlandi")
                    .order_by("created_at")
                    .select_related("teklif", "teklif__malzeme")
                )
                for aday in adaylar:
                    if aday.sanal_depoda_bekleyen > 0:
                        siparis_obj = aday
                        break
        except Exception:
            logger.exception("FIFO eşleşme hatası (DepoTransfer id=%s)", instance.id)

        # 2) TEK KAPI: StockService (idempotent)
        StockService.execute_transfer(
            transfer_id=instance.id,
            ref_type="TRANSFER",
            malzeme=instance.malzeme,
            miktar=instance.miktar,
            kaynak_depo=instance.kaynak_depo,
            hedef_depo=instance.hedef_depo,
            siparis=siparis_obj,
            aciklama=f"Transfer #{instance.id} | {instance.aciklama or ''}",
            tarih=instance.tarih,
        )

        # 3) Sipariş bağını DB'de güncelle (recursive sinyal yok)
        if (instance.bagli_siparis_id is None) and (siparis_obj is not None):
            DepoTransfer.objects.filter(pk=instance.pk).update(bagli_siparis=siparis_obj)

        # 4) Sipariş durum güncelle (teslimat durumu vs)
        if siparis_obj:
            siparis_obj.save()
