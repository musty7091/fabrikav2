from decimal import Decimal
from django.db import transaction

from core.models import FaturaOdeme

@transaction.atomic
def dagit_odeme_faturalara(odeme, faturalar_qs):
    """
    UI değişmeden çalışma mantığı:
    - Kullanıcı faturaları seçer
    - Tek bir ödeme tutarı girer
    - Sistem seçilen faturaları sırayla kapatır (FIFO)
    """

    kalan = Decimal(str(odeme.tutar))

    for fatura in faturalar_qs:
        if kalan <= 0:
            break

        f_kalan = Decimal(str(fatura.kalan_borc))
        if f_kalan <= 0:
            continue

        pay = f_kalan if kalan >= f_kalan else kalan

        FaturaOdeme.objects.create(
            fatura=fatura,
            odeme=odeme,
            tutar=pay,
            para_birimi=odeme.para_birimi,
            kur=getattr(odeme, 'kur', Decimal('1.0')),
            tarih=getattr(odeme, 'tarih', None),
        )

        kalan -= pay

    return kalan  # eğer >0 kalırsa fazla ödeme var demektir
