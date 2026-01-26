from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.models import (
    Tedarikci, Malzeme, Depo, DepoHareket, 
    SatinAlma, Teklif, Hakedis, Fatura, FaturaKalem, 
    Odeme, Kategori, IsKalemi
)

class FabrikaSistemTesti(TestCase):
    def setUp(self):
        """Test ortamı için temel verilerin kurulumu (Setup)"""
        # 1. Yetki Testleri için Süper Kullanıcı
        self.username = 'mimar_tester'
        self.password = 'test12345'
        self.user = User.objects.create_superuser(
            username=self.username, 
            password=self.password, 
            email='test@aeco.com'
        )
        self.client = Client()
        # Giriş yapıldığını doğrula
        login_success = self.client.login(username=self.username, password=self.password)
        self.assertTrue(login_success, "Test kullanıcısı giriş yapamadı!")

        # 2. Temel Tanımlamalar (Master Data)
        self.tedarikci = Tedarikci.objects.create(firma_unvani="Test Tedarik A.Ş.")
        self.depo = Depo.objects.create(isim="Ana Depo", depo_tipi="WAREHOUSE")
        self.kategori = Kategori.objects.create(isim="İnşaat")
        
        self.malzeme = Malzeme.objects.create(
            isim="Test Demir", 
            birim="kg", 
            kdv_orani=20
        )
        
        self.is_kalemi = IsKalemi.objects.create(
            kategori=self.kategori,
            isim="Hafriyat Hizmeti",
            birim="m3",
            kdv_orani=20
        )

    # --- 1. FİNANSAL MATEMATİK VE MODEL TESTLERİ ---

    def test_hakedis_kesinti_ve_net_tutar_hesabi(self):
        """Hakediş save() metodundaki KDV, Stopaj ve Teminat hesaplarını denetler"""
        # Teklif ve Sipariş oluştur
        teklif = Teklif.objects.create(
            tedarikci=self.tedarikci, 
            is_kalemi=self.is_kalemi, 
            miktar=10, 
            birim_fiyat=1000, 
            para_birimi='TRY', 
            kur_degeri=1, 
            kdv_orani=20,
            kdv_dahil_mi=False
        )
        siparis = SatinAlma.objects.create(teklif=teklif, toplam_miktar=10)

        # %50 ilerleme ile hakediş (Brüt: 5000 TL)
        hakedis = Hakedis.objects.create(
            satinalma=siparis, 
            tamamlanma_orani=50, 
            stopaj_orani=5, 
            teminat_orani=10
        )

        # Matematiksel Analiz:
        # Brüt Hakediş: 5000 TL
        # KDV (%20): 1000 TL
        # Stopaj (%5): 250 TL
        # Teminat (%10): 500 TL
        # Net Ödenecek: (5000 + 1000) - (250 + 500) = 5250 TL
        
        self.assertEqual(hakedis.brut_tutar, Decimal('5000.00'))
        self.assertEqual(hakedis.odenecek_net_tutar, Decimal('5250.00'))

    def test_hakedis_yuzde_limit_kontrolu(self):
        """Toplam ilerlemenin %100'ü geçmesini engelleyen validasyonu test eder"""
        teklif = Teklif.objects.create(tedarikci=self.tedarikci, malzeme=self.malzeme, miktar=1, birim_fiyat=100)
        siparis = SatinAlma.objects.create(teklif=teklif, toplam_miktar=1)
        
        # İlk hakediş %70
        Hakedis.objects.create(satinalma=siparis, tamamlanma_orani=70)
        
        # İkinci hakediş %40 (Toplam %110 -> ValidationError fırlatmalı)
        hakedis2 = Hakedis(satinalma=siparis, tamamlanma_orani=40)
        with self.assertRaises(ValidationError):
            hakedis2.full_clean()

    # --- 2. STOK VE HAREKET TESTLERİ ---

    def test_malzeme_stok_ve_iade_mantigi(self):
        """Giriş, çıkış ve iade hareketlerinin stok toplamına etkisini denetler"""
        # 100 birim giriş
        DepoHareket.objects.create(malzeme=self.malzeme, depo=self.depo, miktar=100, islem_turu='giris')
        # 30 birim çıkış
        DepoHareket.objects.create(malzeme=self.malzeme, depo=self.depo, miktar=30, islem_turu='cikis')
        # 10 birim iade (stoktan düşer)
        DepoHareket.objects.create(malzeme=self.malzeme, depo=self.depo, miktar=10, islem_turu='iade')
        
        self.malzeme.refresh_from_db()
        # 100 - 30 - 10 = 60
        self.assertEqual(self.malzeme.stok, Decimal('60.00'))

    # --- 3. FORM VE VERİ KAYIT (POST) TESTLERİ ---

    def test_serbest_fatura_kayit_dogrulamasi(self):
        """Form üzerinden (ManagementForm dahil) fatura kaydını ve KDV hesaplamasını doğrular"""
        url = reverse('serbest_fatura_girisi')
        # 'kdv_dahil_mi' alanı False olması için gönderilmemelidir.
        data = {
            'tedarikci': self.tedarikci.id,
            'depo': self.depo.id,
            'fatura_no': 'TEST-001',
            'tarih': timezone.now().date(),
            'kalemler-TOTAL_FORMS': '1',
            'kalemler-INITIAL_FORMS': '0',
            'kalemler-MIN_NUM_FORMS': '0',
            'kalemler-MAX_NUM_FORMS': '1000',
            'kalemler-0-malzeme': self.malzeme.id,
            'kalemler-0-miktar': '5',
            'kalemler-0-fiyat': '100',
            'kalemler-0-kdv_oran': '20',
            # 'kalemler-0-kdv_dahil_mi' gönderilmediği için False sayılır.
        }
        response = self.client.post(url, data, follow=True)
        
        self.assertEqual(response.status_code, 200)
        fatura = Fatura.objects.filter(fatura_no='TEST-001').first()
        self.assertIsNotNone(fatura, "Fatura veritabanına kaydedilemedi.")
        
        # Matematiksel toplam kontrolü (5 * 100 = 500 Ara, +%20 KDV = 600 Genel)
        self.assertEqual(fatura.genel_toplam, Decimal('600.00'))

    # --- 4. ENTEGRASYON VE ARAYÜZ ERİŞİM TESTLERİ ---

    def test_sayfa_yükleme_ve_erisim(self):
        """Tüm kritik sayfaların teknik olarak yüklendiğini (200 OK) denetler"""
        urls = [
            'dashboard', 'fatura_listesi', 'siparis_listesi', 
            'stok_listesi', 'gider_listesi', 'cari_ekstresi',
            'finans_dashboard', 'odeme_dashboard', 'depo_dashboard'
        ]
        for name in urls:
            response = self.client.get(reverse(name), follow=True)
            self.assertEqual(response.status_code, 200, f"Sayfa yükleme hatası: {name}")

    def test_odeme_cek_durum_kontrolu(self):
        """Ödeme kaydının ve çek özelliklerinin varsayılanlarını test eder"""
        odeme = Odeme.objects.create(
            tedarikci=self.tedarikci,
            tutar=1000,
            para_birimi='TRY',
            odeme_turu='cek',
            vade_tarihi=timezone.now().date()
        )
        self.assertEqual(odeme.odeme_turu, 'cek')
        # Yeni ödeme çek ise varsayılan olarak tahsil edilmemiş olmalı
        self.assertFalse(odeme.is_cek_odendi)