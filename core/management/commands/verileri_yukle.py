from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import (
    Depo, Malzeme, Tedarikci, Kategori, 
    DepoHareket, IsKalemi, GiderKategorisi
)

class Command(BaseCommand):
    help = 'Sisteme test verileri yükler (Fabrika Kurulumu - Yeni Yapı)'

    def handle(self, *args, **kwargs):
        self.stdout.write('🧹 Temizlik yapılıyor (Çakışma olmaması için)...')
        # Temizle komutunu çağırmak yerine manuel siliyoruz (daha güvenli)
        DepoHareket.objects.all().delete()
        Malzeme.objects.all().delete()
        Depo.objects.all().delete()
        Tedarikci.objects.all().delete()
        Kategori.objects.all().delete()

        self.stdout.write('🏗️ Depolar kuruluyor...')
        
        # 1. SANAL DEPO (Zorunlu - is_sanal=True)
        sanal_depo = Depo.objects.create(
            isim="Tedarikçi Sanal Depo", 
            adres="Sanal (Muhasebe Kaydı İçin)", 
            is_sanal=True
        )
        
        # 2. FİZİKSEL DEPOLAR (is_sanal=False)
        merkez = Depo.objects.create(isim="Merkez Depo", adres="İstanbul Lojistik", is_sanal=False)
        santiye = Depo.objects.create(isim="Şantiye A Blok", adres="Proje Sahası", is_sanal=False)

        self.stdout.write('📂 Kategoriler tanımlanıyor...')
        # İş Kalemleri için kategoriler
        k_insaat = Kategori.objects.create(isim="Kaba İnşaat")
        k_mekanik = Kategori.objects.create(isim="Mekanik Tesisat")

        self.stdout.write('🚚 Tedarikçiler ekleniyor...')
        # DÜZELTME BURADA YAPILDI (yetkili -> yetkili_kisi)
        t1 = Tedarikci.objects.create(firma_unvani="Akçansa Beton A.Ş.", yetkili_kisi="Ahmet Yılmaz", telefon="0532 100 20 30")
        t2 = Tedarikci.objects.create(firma_unvani="Öznur Kablo", yetkili_kisi="Mehmet Demir", telefon="0533 900 80 70")
        t3 = Tedarikci.objects.create(firma_unvani="Koçtaş Kurumsal", yetkili_kisi="Müşteri Hizmetleri", telefon="444 55 66")

        self.stdout.write('📦 Malzemeler tanımlanıyor...')
        
        # Malzeme 1: Demir (İnşaat)
        m1 = Malzeme.objects.create(
            isim="Ø16 Nervürlü Demir", 
            kategori='insaat', # models.py choice alanı
            birim='ton',       # models.py choice alanı
            marka="Kardemir", 
            kritik_stok=10
        )
        
        # Malzeme 2: Kablo (Elektrik)
        m2 = Malzeme.objects.create(
            isim="3x2.5 NYM Kablo", 
            kategori='elektrik', 
            birim='mt', 
            marka="Öznur", 
            kritik_stok=500
        )

        # Malzeme 3: Çimento (Genel)
        m3 = Malzeme.objects.create(
            isim="Portland Çimento (50kg)", 
            kategori='insaat', 
            birim='adet', 
            marka="Akçansa", 
            kritik_stok=50
        )

        self.stdout.write('📈 Stok Hareketleri (Açılış Stokları)...')
        
        # Örnek 1: Merkeze açılış stoğu (Fiziksel var)
        DepoHareket.objects.create(
            malzeme=m1, 
            depo=merkez, 
            islem_turu='giris', 
            miktar=50, 
            aciklama="Devir / Açılış Stoğu",
            tarih=timezone.now()
        )

        # Örnek 2: Şantiyeye biraz kablo gönderilmiş olsun
        DepoHareket.objects.create(
            malzeme=m2, 
            depo=santiye, 
            islem_turu='giris', 
            miktar=200, 
            aciklama="Şantiye Açılış Malzemesi",
            tarih=timezone.now()
        )

        self.stdout.write(self.style.SUCCESS('✅ SİSTEM HAZIR! Sanal Depo ve Test Verileri Yüklendi.'))