from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from decimal import Decimal

from core.models import Kategori, IsKalemi, Tedarikci, Depo, Malzeme


class Command(BaseCommand):
    help = "Demo veriler oluşturur: 3 malzeme, 3 tedarikçi, 3 iş kalemi, 4 depo."

    @transaction.atomic
    def handle(self, *args, **options):
        # 1) Kategori
        kat, _ = Kategori.objects.get_or_create(isim="Genel İmalat")

        # 2) 3 İş Kalemi
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
                    "aciklama": "Demo iş kalemi",
                },
            )

        # 3) 3 Tedarikçi
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

        # 4) 4 Depo
        # Not: Senin Depo.save() boolean'ları depo_tipi ile senkronluyor; burada doğru depo_tipi veriyoruz.
        depolar = [
            ("Merkez Depo", "Lefkoşa / Merkez", "WAREHOUSE"),
            ("Girne Şantiye", "Girne / Şantiye", "SITE"),
            ("Tedarikçi Deposu (Sanal)", "Vendor Location", "VENDOR"),
            ("Sarf Yeri / Uygulama", "Saha Kullanım", "CONSUMPTION"),
        ]
        for isim, adres, depo_tipi in depolar:
            Depo.objects.get_or_create(
                isim=isim,
                defaults={
                    "adres": adres,
                    "depo_tipi": depo_tipi,
                },
            )

        # 5) 3 Malzeme
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
                    "aciklama": "Demo malzeme",
                },
            )

        self.stdout.write(self.style.SUCCESS("✅ Demo veriler oluşturuldu (veya zaten vardı)."))
        self.stdout.write("Kontrol: Admin panelde Depo / Malzeme / Tedarikçi / İş Kalemi listelerine bakabilirsin.")
