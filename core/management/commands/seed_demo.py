# core/management/commands/seed_demo.py

from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal

# Modellerinizi import ediyoruz
from core.models import Kategori, IsKalemi, Tedarikci, Depo, Malzeme

class Command(BaseCommand):
    help = "Demo veriler oluşturur: Malzemeler, Tedarikçiler, İş Kalemleri ve Depolar."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("⏳ Demo veri oluşturma işlemi başladı...")

        # ---------------------------------------------------------
        # 1) Kategori (İş Kalemleri İçin)
        # ---------------------------------------------------------
        kat, _ = Kategori.objects.get_or_create(isim="Genel İmalat")

        # ---------------------------------------------------------
        # 2) 3 Adet İş Kalemi (Hizmet)
        # ---------------------------------------------------------
        is_kalemleri = [
            ("Beton Dökümü", Decimal("100.00"), "m3"),
            ("Demir Bağlama", Decimal("500.00"), "kg"),
            ("Elektrik Tesisatı", Decimal("1.00"), "goturu"),
        ]
        for isim, hedef_miktar, birim in is_kalemleri:
            IsKalemi.objects.get_or_create(
                kategori=kat,
                isim=isim,
                defaults={
                    "hedef_miktar": hedef_miktar,
                    "birim": birim,
                    "kdv_orani": 20,
                    "aciklama": "Demo iş kalemi (Otomatik oluşturuldu)",
                },
            )
        self.stdout.write(" - İş kalemleri tamam.")

        # ---------------------------------------------------------
        # 3) 3 Adet Tedarikçi
        # ---------------------------------------------------------
        tedarikciler = [
            ("Atlas Yapı Market Ltd.", "Ali Yılmaz", "0532 000 00 01", "Lefkoşa"),
            ("Kıbrıs Elektrik Tedarik", "Ayşe Demir", "0533 000 00 02", "Girne"),
            ("Demirci Hırdavat", "Mehmet Kaya", "0534 000 00 03", "Mağusa"),
        ]
        for unvan, yetkili, tel, adres in tedarikciler:
            Tedarikci.objects.get_or_create(
                firma_unvani=unvan,
                defaults={
                    "yetkili_kisi": yetkili,
                    "telefon": tel,
                    "adres": adres,
                },
            )
        self.stdout.write(" - Tedarikçiler tamam.")

        # ---------------------------------------------------------
        # 4) 4 Farklı Tipte Depo
        # ---------------------------------------------------------
        # Not: Sizin Depo modelinizdeki 'save' metodu, depo_tipi'ne göre
        # is_sanal ve is_kullanim_yeri alanlarını otomatik ayarlayacaktır.
        depolar = [
            ("Merkez Depo", "Lefkoşa / Merkez", "WAREHOUSE"),          # Fiziksel
            ("Girne Şantiye", "Girne / Şantiye", "SITE"),              # Şantiye
            ("Tedarikçi Deposu (Sanal)", "Vendor Location", "VENDOR"), # Sanal
            ("Sarf Yeri / Uygulama", "Saha Kullanım", "CONSUMPTION"),  # Tüketim
        ]
        for isim, adres, depo_tipi in depolar:
            Depo.objects.get_or_create(
                isim=isim,
                defaults={
                    "adres": adres,
                    "depo_tipi": depo_tipi,
                },
            )
        self.stdout.write(" - Depolar tamam.")

        # ---------------------------------------------------------
        # 5) 3 Adet Malzeme
        # ---------------------------------------------------------
        malzemeler = [
            ("Ø14 İnşaat Demiri", "insaat", "Kardemir", "kg", 20, Decimal("200")),
            ("CEM I 42.5 Çimento", "insaat", "Akçansa", "kg", 20, Decimal("50")),
            ("NYM 3x2.5 Kablo", "elektrik", "Prysmian", "mt", 20, Decimal("300")),
        ]
        for isim, kategori, marka, birim, kdv_orani, kritik in malzemeler:
            Malzeme.objects.get_or_create(
                isim=isim,
                defaults={
                    "kategori": kategori,
                    "marka": marka,
                    "birim": birim,
                    "kdv_orani": kdv_orani,
                    "kritik_stok": kritik,
                    "aciklama": "Demo malzeme (Otomatik oluşturuldu)",
                },
            )
        self.stdout.write(" - Malzemeler tamam.")

        self.stdout.write(self.style.SUCCESS("✅ TÜM DEMO VERİLER BAŞARIYLA OLUŞTURULDU!"))