from django.core.management.base import BaseCommand
from core.models import GiderKategorisi

class Command(BaseCommand):
    help = 'Standart gider kategorilerini yükler.'

    def handle(self, *args, **kwargs):
        GIDERLER = [
            "Seyahat & Ulaşım (Uçak, Yakıt, Taksi)",
            "Konaklama & Otel",
            "Yeme & İçme & Temsil Ağırlama",
            "Fuar & Pazarlama & Reklam",
            "Resmi Harçlar & Vergiler & Noter",
            "Personel Maaş & Avans",
            "Ofis Kırtasiye & Sarf Malzeme",
        ]

        for isim in GIDERLER:
            GiderKategorisi.objects.get_or_create(isim=isim)
            
        self.stdout.write(self.style.SUCCESS('Gider kategorileri başarıyla yüklendi.'))