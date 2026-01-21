from django.core.management.base import BaseCommand
from django.db import transaction
# GenelGider import listesinden çıkarıldı
from core.models import (
    Kategori, Depo, Tedarikci, Malzeme, IsKalemi,
    MalzemeTalep, Teklif, SatinAlma,
    DepoTransfer, DepoHareket,
    Hakedis, Odeme, Fatura, FaturaKalem,
    GiderKategorisi
)

class Command(BaseCommand):
    help = "Veritabanındaki tüm iş verilerini temizler (Kullanıcılar hariç)"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("🧹 Temizlik işlemi başlıyor...")

        # SİLME SIRASI ÇOK ÖNEMLİDİR!
        # Bağımlı olan (Çocuk) tablolardan, Bağımsız olan (Ebeveyn) tablolara doğru silmeliyiz.

        # 1. En Uçtaki Detaylar (Bağımlılıkları en çok olanlar)
        self.sil(DepoHareket, "Depo Hareketleri")
        self.sil(FaturaKalem, "Fatura Kalemleri")
        self.sil(DepoTransfer, "Depo Transferleri")
        
        # 2. Finansal İşlemler (Tedarikçi ve Siparişe bağlılar)
        self.sil(Odeme, "Ödemeler")
        self.sil(Hakedis, "Hakedişler")
        self.sil(Fatura, "Faturalar") # ÖNEMLİ: Fatura silinmeden Tedarikçi silinemez!
        
        # 3. Satınalma Süreci (Tersten başa)
        self.sil(SatinAlma, "Siparişler (Satınalma)")
        self.sil(Teklif, "Teklifler")
        self.sil(MalzemeTalep, "Talepler")

        # 4. Ana Tanımlar (Artık bunları silmek güvenli)
        self.sil(IsKalemi, "İş Kalemleri")
        self.sil(Malzeme, "Malzemeler")
        self.sil(Depo, "Depolar")
        self.sil(Tedarikci, "Tedarikçiler")
        self.sil(GiderKategorisi, "Gider Kategorileri")
        self.sil(Kategori, "Kategoriler")

        self.stdout.write(self.style.SUCCESS("✅ TÜM VERİLER BAŞARIYLA SİLİNDİ! (Sistem sıfırlandı)"))

    def sil(self, model, isim):
        # Modelin veritabanında var olup olmadığını kontrol et (Emniyet sübabı)
        try:
            sayi = model.objects.count()
            model.objects.all().delete()
            self.stdout.write(f" - {isim} silindi: {sayi} adet")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f" ! {isim} silinirken uyarı: {e}"))