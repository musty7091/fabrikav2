# core/services.py
from django.db import transaction
from core.models import DepoHareket

class StockService:
    @staticmethod
    @transaction.atomic
    def execute_transfer(malzeme, miktar, kaynak_depo, hedef_depo, siparis=None, aciklama="", tarih=None):
        """
        Sistemde stok değiştiren TEK KAPI.
        """
        from django.utils import timezone
        islem_tarihi = tarih or timezone.now().date()

        # 1. Kaynak Depodan ÇIKIŞ
        DepoHareket.objects.create(
            malzeme=malzeme,
            depo=kaynak_depo,
            miktar=miktar,
            islem_turu='cikis',
            siparis=siparis,
            tarih=islem_tarihi,
            aciklama=f"ÇIKIŞ: {aciklama}"
        )

        # 2. Hedef Depoya GİRİŞ
        DepoHareket.objects.create(
            malzeme=malzeme,
            depo=hedef_depo,
            miktar=miktar,
            islem_turu='giris',
            siparis=siparis,
            tarih=islem_tarihi,
            aciklama=f"GİRİŞ: {aciklama}"
        )
        return True