from django.core.management.base import BaseCommand
from core.models import Kategori, IsKalemi
from django.db import transaction

class Command(BaseCommand):
    help = 'Fabrika projesi için varsayılan kategori ve iş kalemlerini yükler.'

    def handle(self, *args, **kwargs):
        # Büyük Fabrika Projesi İş Kırılım Yapısı (WBS)
        FABRIKA_VERISI = {
            "1. GENEL GİDERLER & HAZIRLIK": [
                ("Proje Yönetimi ve Ofis Giderleri", "set"),
                ("Şantiye Mobilizasyonu (Konteyner, Çit, Güvenlik)", "set"),
                ("Geçici Elektrik ve Su Tesisatı", "set"),
                ("İş Sağlığı ve Güvenliği Önlemleri", "adam_saat"),
            ],
            "2. HAFRİYAT & ALTYAPI": [
                ("Yüzeysel Kazı ve Sıyırma", "m3"),
                ("Temel Kazısı", "m3"),
                ("Dolgu ve Sıkıştırma (Stabilize)", "m3"),
                ("Yağmur Suyu Drenaj Hattı", "mt"),
                ("Pis Su (Kanalizasyon) Hattı", "mt"),
                ("Kablo Kanalları ve Menholler", "mt"),
            ],
            "3. KABA YAPI (İNŞAAT)": [
                ("Grobeteon Dökülmesi (C20)", "m3"),
                ("Temel ve Perde Yalıtımı (Bohçalama)", "m2"),
                ("Temel Betonu (C35/C40)", "m3"),
                ("İnşaat Demiri (Donatı)", "ton"),
                ("Kalıp İşçiliği ve Malzemesi", "m2"),
                ("Saha Betonu ve Yüzey Sertleştirici", "m2"),
                ("Çelik Konstrüksiyon (Kolon, Kiriş, Makas)", "ton"),
                ("Çelik Çatı ve Cephe Karkası", "ton"),
            ],
            "4. ÇATI & CEPHE KAPLAMA": [
                ("Çatı Sandviç Panel Kaplama (Taşyünü)", "m2"),
                ("Cephe Sandviç Panel Kaplama", "m2"),
                ("Polikarbon Işıklıklar ve Duman Kapakları", "m2"),
                ("Yağmur İniş Boruları ve Oluklar", "mt"),
                ("Endüstriyel Seksiyonel Kapılar", "adet"),
                ("Personel ve Acil Çıkış Kapıları", "adet"),
            ],
            "5. İNCE YAPI & MİMARİ": [
                ("İç Duvar Bölmeleri (Gazbeton/Alçıpan)", "m2"),
                ("Duvar Sıva ve Boya İşleri", "m2"),
                ("Asma Tavan İşleri (Ofis Alanları)", "m2"),
                ("Seramik ve Zemin Kaplama (Islak Hacim/Ofis)", "m2"),
                ("Alüminyum/PVC Doğramalar ve Camlar", "m2"),
                ("Ofis Mobilyaları ve Tefrişat", "set"),
            ],
            "6. MEKANİK TESİSAT": [
                ("Sıhhi Tesisat (Temiz Su/Pis Su)", "set"),
                ("Yangın Dolapları ve Hidrant Hattı", "mt"),
                ("Sprinkler (Yağmurlama) Sistemi", "m2"),
                ("Yangın Pompa Grubu", "set"),
                ("Isıtma/Soğutma Sistemleri (VRF/Klima Santrali)", "set"),
                ("Havalandırma Kanalları ve Fanlar", "m2"),
                ("Basınçlı Hava Tesisatı (Kompresör Dahil)", "set"),
                ("Proses Suyu / Soğutma Kulesi Tesisatı", "set"),
                ("Asansörler (Yük/Personel)", "adet"),
                ("Vinç Sistemleri (Gezer Köprülü Vinç)", "adet"),
            ],
            "7. ELEKTRİK TESİSAT": [
                ("OG Hücreleri ve Trafo Köşkü", "set"),
                ("Ana Dağıtım Panoları (ADP)", "adet"),
                ("Tali Dağıtım Panoları ve Kablolama", "mt"),
                ("Kablo Tavaları ve Busbar Sistemleri", "mt"),
                ("Fabrika İçi Aydınlatma (Yüksek Tavan LED)", "adet"),
                ("Acil Durum ve Yönlendirme Aydınlatması", "adet"),
                ("Jeneratör Grubu ve Transfer Panosu", "set"),
                ("Topraklama ve Yıldırımdan Korunma (Paratoner)", "set"),
            ],
             "8. ZAYIF AKIM SİSTEMLERİ": [
                ("Yangın Algılama ve İhbar Sistemi", "adet"),
                ("Data ve Telefon Altyapısı (Yapısal Kablolama)", "mt"),
                ("CCTV Kamera Güvenlik Sistemi", "set"),
                ("Kartlı Geçiş ve Turnike Sistemleri", "set"),
                ("Seslendirme ve Acil Anons Sistemi", "set"),
            ],
            "9. DIŞ SAHA & PEYZAJ": [
                ("Saha Beton Yollar ve Otoparklar", "m2"),
                ("Çevre Duvarı ve Tel Çit", "mt"),
                ("Ana Giriş Kapısı ve Güvenlik Kulübesi", "set"),
                ("Peyzaj ve Bitkilendirme", "m2"),
                ("Dış Saha Aydınlatma Direkleri", "adet"),
            ]
        }

        self.stdout.write(self.style.WARNING('Veritabanı yükleniyor... Lütfen bekleyiniz.'))

        # İşlemi güvenli yapmak için transaction (atomik işlem) kullanıyoruz.
        # Bir hata olursa tüm işlemi geri alır, yarım veri kalmaz.
        try:
            with transaction.atomic():
                kategori_sayac = 0
                kalem_sayac = 0

                for kat_isim, kalemler in FABRIKA_VERISI.items():
                    # Kategoriyi oluştur veya varsa getir (get_or_create)
                    # Bu sayede scripti iki kere çalıştırsanız bile çift kayıt olmaz.
                    kategori_obj, created = Kategori.objects.get_or_create(isim=kat_isim)
                    if created:
                        kategori_sayac += 1
                        self.stdout.write(f"Yeni Kategori: {kat_isim}")

                    for kalem_adi, birim in kalemler:
                        # İş kalemini oluştur
                        _, kalem_created = IsKalemi.objects.get_or_create(
                            kategori=kategori_obj,
                            isim=kalem_adi,
                            defaults={'birim': birim, 'hedef_miktar': 1}
                        )
                        if kalem_created:
                            kalem_sayac += 1

            self.stdout.write(self.style.SUCCESS(f'\nBAŞARILI! Toplam {kategori_sayac} yeni kategori ve {kalem_sayac} yeni iş kalemi yüklendi.'))
            self.stdout.write(self.style.SUCCESS('Artık icmal ekranınız dolu dolu görünecek.'))

        except Exception as e:
             self.stdout.write(self.style.ERROR(f'HATA OLUŞTU: İşlem geri alındı. Detay: {e}'))