# core/services.py
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Q
from django.core.exceptions import ValidationError

from core.models import DepoHareket


class StockService:
    @staticmethod
    @transaction.atomic
    def execute_transfer(
        *,
        transfer_id=None,          # idempotency anahtarı (DepoTransfer.id gibi)
        malzeme=None,
        miktar=None,
        kaynak_depo=None,
        hedef_depo=None,
        siparis=None,
        aciklama="",
        tarih=None,
        ref_type="TRANSFER",       # TRANSFER / FATURA / MANUEL / IADE
    ):
        """
        Sistemde stok değiştiren TEK KAPI.

        - Idempotency: transfer_id verilirse, aynı belge için OUT/IN hareketleri 2. kez yazılamaz.
        - Güvenli stok: Kaynak depoda yeterli stok yoksa işlem durur.
        """

        if malzeme is None or kaynak_depo is None or hedef_depo is None:
            raise ValidationError("StockService: malzeme/kaynak_depo/hedef_depo zorunludur.")
        if miktar is None:
            raise ValidationError("StockService: miktar zorunludur.")

        miktar = Decimal(str(miktar))
        if miktar <= 0:
            raise ValidationError("StockService: miktar 0'dan büyük olmalıdır.")

        from django.utils import timezone
        islem_tarihi = tarih or timezone.now().date()

        # --- yardımcı: depo bazlı bakiye ---
        def depo_bakiye(d, m):
            agg = DepoHareket.objects.filter(depo=d, malzeme=m).aggregate(
                giris=Sum("miktar", filter=Q(islem_turu="giris")),
                cikis=Sum("miktar", filter=Q(islem_turu="cikis")),
                iade=Sum("miktar", filter=Q(islem_turu="iade")),
            )
            giris = agg["giris"] or Decimal("0")
            cikis = agg["cikis"] or Decimal("0")
            iade = agg["iade"] or Decimal("0")
            return giris - cikis - iade

        # --- stok yeterlilik kontrolü (kaynak depo) ---
        mevcut = depo_bakiye(kaynak_depo, malzeme)
        if mevcut < miktar:
            raise ValidationError(
                f"Yetersiz stok: '{malzeme}' | Kaynak depo '{kaynak_depo}' bakiyesi {mevcut}, istenen {miktar}."
            )

        # --- idempotency anahtarları ---
        use_ref = transfer_id is not None

        # 1) Kaynak depodan ÇIKIŞ (OUT)
        if use_ref:
            DepoHareket.objects.get_or_create(
                ref_type=ref_type,
                ref_id=int(transfer_id),
                ref_direction="OUT",
                malzeme=malzeme,
                depo=kaynak_depo,
                defaults=dict(
                    miktar=miktar,
                    islem_turu="cikis",
                    siparis=siparis,
                    tarih=islem_tarihi,
                    aciklama=f"ÇIKIŞ: {aciklama}",
                ),
            )
        else:
            DepoHareket.objects.create(
                malzeme=malzeme,
                depo=kaynak_depo,
                miktar=miktar,
                islem_turu="cikis",
                siparis=siparis,
                tarih=islem_tarihi,
                aciklama=f"ÇIKIŞ: {aciklama}",
            )

        # 2) Hedef depoya GİRİŞ (IN)
        # Not: hedef depo CONSUMPTION ise bile "giriş" yazıyoruz ki hareket kaydı görülsün.
        #      Malzeme.stok zaten kullanım yerlerini hariç tuttuğu için stok şişmez.
        if use_ref:
            DepoHareket.objects.get_or_create(
                ref_type=ref_type,
                ref_id=int(transfer_id),
                ref_direction="IN",
                malzeme=malzeme,
                depo=hedef_depo,
                defaults=dict(
                    miktar=miktar,
                    islem_turu="giris",
                    siparis=siparis,
                    tarih=islem_tarihi,
                    aciklama=f"GİRİŞ: {aciklama}",
                ),
            )
        else:
            DepoHareket.objects.create(
                malzeme=malzeme,
                depo=hedef_depo,
                miktar=miktar,
                islem_turu="giris",
                siparis=siparis,
                tarih=islem_tarihi,
                aciklama=f"GİRİŞ: {aciklama}",
            )

        return True
