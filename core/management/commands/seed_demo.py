# core/management/commands/seed_demo.py

from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
import random
from django.utils.text import slugify

from core.models import Kategori, IsKalemi, Tedarikci, Depo, Malzeme

# -----------------------------
# Yardımcılar
# -----------------------------
def d(x: str) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))

def pick(rng, items):
    return items[rng.randrange(0, len(items))]

def phone(rng):
    # KKTC/TR demo format
    return f"05{rng.randrange(30, 50)} {rng.randrange(100,999)} {rng.randrange(10,99)} {rng.randrange(10,99)}"

def make_code(prefix: str, name: str, rng) -> str:
    base = slugify(name)[:12].upper().replace("-", "")
    return f"{prefix}-{base}-{rng.randrange(100,999)}"

# -----------------------------
# Command
# -----------------------------
class Command(BaseCommand):
    help = "Zengin demo veriler oluşturur: Kategori, İş Kalemi, Tedarikçi, Depo, Malzeme."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=42, help="Deterministik demo üretimi için seed (default: 42)")
        parser.add_argument("--reset", action="store_true", help="Önce demo tablolarını temizleyip yeniden oluştur")
        parser.add_argument("--small", action="store_true", help="Daha az kayıt üret (hızlı demo)")

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(options["seed"])
        small = options["small"]

        self.stdout.write("⏳ Demo veri oluşturma işlemi başladı...")

        if options["reset"]:
            self._reset_demo_tables()

        # 1) Kategoriler
        kategori_isimleri = [
            "Genel İmalat",
            "İnşaat İşleri",
            "Elektrik & Mekanik",
            "Tadilat",
            "Bakım Onarım",
        ]
        kategoriler = []
        for isim in kategori_isimleri:
            obj, _ = Kategori.objects.get_or_create(isim=isim)
            kategoriler.append(obj)
        self.stdout.write(f" - Kategori tamam: {len(kategoriler)}")

        # 2) İş Kalemleri
        # (isim, birim, hedef_min, hedef_max, kdv)
        is_kalemi_havuzu = [
            ("Beton Dökümü", "m3", 10, 250, 20),
            ("Demir Bağlama", "kg", 500, 50000, 20),
            ("Kalıp İşçiliği", "m2", 50, 5000, 20),
            ("Sıva Uygulaması", "m2", 50, 8000, 20),
            ("Boya Uygulaması", "m2", 50, 8000, 20),
            ("Seramik Döşeme", "m2", 20, 2000, 20),
            ("Alçıpan Tavan", "m2", 20, 2500, 20),
            ("Elektrik Tesisatı", "goturu", 1, 1, 20),
            ("Kablo Çekimi", "mt", 100, 20000, 20),
            ("Pano Montajı", "adet", 1, 30, 20),
            ("Mekanik Montaj", "goturu", 1, 1, 20),
            ("Su Tesisatı", "goturu", 1, 1, 20),
        ]

        is_kalem_sayisi = 12 if not small else 6
        created_count = 0
        for kat in kategoriler:
            # kategori başına 5-8 (small ise 3-4)
            per_cat = rng.randrange(5, 9) if not small else rng.randrange(3, 5)
            chosen = rng.sample(is_kalemi_havuzu, k=min(per_cat, len(is_kalemi_havuzu)))

            for isim, birim, mn, mx, kdv in chosen:
                hedef = Decimal(str(rng.randrange(mn, mx + 1))) if mn != mx else Decimal(str(mn))
                obj, created = IsKalemi.objects.get_or_create(
                    kategori=kat,
                    isim=f"{isim} ({kat.isim})" if not small else f"{isim}",
                    defaults={
                        "hedef_miktar": hedef,
                        "birim": birim,
                        "kdv_orani": kdv,
                        "aciklama": "Demo iş kalemi (otomatik üretildi)",
                    },
                )
                if created:
                    created_count += 1
        self.stdout.write(f" - İş kalemleri tamam: +{created_count}")

        # 3) Tedarikçiler
        firma_adlari = [
            "Atlas Yapı Market Ltd.",
            "Kıbrıs Elektrik Tedarik",
            "Demirci Hırdavat",
            "Akdeniz İnşaat Malz.",
            "Doğu Teknik",
            "Mavi Kablo A.Ş.",
            "Usta Yapı",
            "Lefkoşa Beton",
            "Girne Elektrik",
            "Mağusa Hırdavat",
            "Kuzey Kimya",
            "Ada Yapı Sistemleri",
        ]
        yetkililer = ["Ali Yılmaz", "Ayşe Demir", "Mehmet Kaya", "Serkan Arslan", "Zeynep Şahin", "Hakan Koç"]
        sehirler = ["Lefkoşa", "Girne", "Mağusa", "Güzelyurt", "İskele"]

        target_ted = 12 if not small else 6
        created_ted = 0
        for i in range(target_ted):
            unvan = firma_adlari[i % len(firma_adlari)]
            yetkili = pick(rng, yetkililer)
            tel = phone(rng)
            adres = f"{pick(rng, sehirler)} / {pick(rng, ['Merkez', 'Sanayi', 'Şantiye', 'Organize', 'Çarşı'])}"

            _, created = Tedarikci.objects.get_or_create(
                firma_unvani=unvan,
                defaults={
                    "yetkili_kisi": yetkili,
                    "telefon": tel,
                    "adres": adres,
                },
            )
            if created:
                created_ted += 1
        self.stdout.write(f" - Tedarikçiler tamam: +{created_ted}")

        # 4) Depolar
        depo_tanimlari = [
            ("Merkez Depo", "Lefkoşa / Merkez", "WAREHOUSE"),
            ("Girne Şantiye", "Girne / Şantiye", "SITE"),
            ("Mağusa Şantiye", "Mağusa / Şantiye", "SITE"),
            ("Tedarikçi Deposu (Sanal)", "Vendor Location", "VENDOR"),
            ("Sarf Yeri / Uygulama", "Saha Kullanım", "CONSUMPTION"),
        ]
        created_depo = 0
        for isim, adres, depo_tipi in depo_tanimlari if not small else depo_tanimlari[:3]:
            _, created = Depo.objects.get_or_create(
                isim=isim,
                defaults={"adres": adres, "depo_tipi": depo_tipi},
            )
            if created:
                created_depo += 1
        self.stdout.write(f" - Depolar tamam: +{created_depo}")

        # 5) Malzemeler
        malzeme_havuzu = [
            # (isim, kategori, marka, birim, kdv, kritik_min, kritik_max)
            ("Ø8 İnşaat Demiri", "insaat", "Kardemir", "kg", 20, 200, 3000),
            ("Ø10 İnşaat Demiri", "insaat", "Kardemir", "kg", 20, 200, 3000),
            ("Ø12 İnşaat Demiri", "insaat", "Kardemir", "kg", 20, 200, 3000),
            ("Ø14 İnşaat Demiri", "insaat", "Kardemir", "kg", 20, 200, 3000),
            ("Ø16 İnşaat Demiri", "insaat", "Kardemir", "kg", 20, 200, 3000),
            ("CEM I 42.5 Çimento", "insaat", "Akçansa", "kg", 20, 50, 2000),
            ("CEM II 32.5 Çimento", "insaat", "Akçansa", "kg", 20, 50, 2000),
            ("Hazır Beton C25", "insaat", "Lefkoşa Beton", "m3", 20, 5, 200),
            ("Hazır Beton C30", "insaat", "Lefkoşa Beton", "m3", 20, 5, 200),
            ("Tuğla (13.5)", "insaat", "Ada Tuğla", "adet", 20, 500, 10000),
            ("Bims Blok", "insaat", "Ada Bims", "adet", 20, 300, 8000),
            ("OSB Levha 18mm", "insaat", "Kastamonu", "adet", 20, 10, 300),
            ("Kontrplak 18mm", "insaat", "Yıldız Entegre", "adet", 20, 10, 300),
            ("Çivi 2.5\"", "insaat", "Vidalama", "kg", 20, 5, 200),
            ("Vida 4x40", "insaat", "Vidalama", "kutu", 20, 5, 150),
            ("NYM 3x2.5 Kablo", "elektrik", "Prysmian", "mt", 20, 100, 5000),
            ("NYM 3x1.5 Kablo", "elektrik", "Prysmian", "mt", 20, 100, 5000),
            ("TTR 3x2.5 Kablo", "elektrik", "Nexans", "mt", 20, 100, 5000),
            ("Pano (12 Modül)", "elektrik", "Schneider", "adet", 20, 2, 100),
            ("Otomat Sigorta 16A", "elektrik", "ABB", "adet", 20, 10, 500),
            ("Otomat Sigorta 25A", "elektrik", "ABB", "adet", 20, 10, 500),
            ("Kaçak Akım Rölesi 40A", "elektrik", "Schneider", "adet", 20, 2, 100),
            ("LED Panel 60x60", "elektrik", "Philips", "adet", 20, 5, 400),
            ("Priz (Topraklı)", "elektrik", "Viko", "adet", 20, 20, 1000),
            ("Anahtar", "elektrik", "Viko", "adet", 20, 20, 1000),
            ("PVC Boru 20mm", "mekanik", "Firat", "mt", 20, 50, 3000),
            ("PPRC Boru 25mm", "mekanik", "Wavin", "mt", 20, 50, 3000),
            ("Dirsek 25mm", "mekanik", "Wavin", "adet", 20, 50, 2000),
            ("Küresel Vana 1\"", "mekanik", "ECA", "adet", 20, 5, 300),
            ("Silikon", "sarf", "Soudal", "adet", 20, 5, 200),
            ("Derz Dolgu", "sarf", "Weber", "kg", 20, 25, 1000),
            ("Boya (İç Cephe)", "sarf", "Filli Boya", "lt", 20, 20, 1000),
            ("Astar", "sarf", "Filli Boya", "lt", 20, 10, 500),
        ]

        target_malz = len(malzeme_havuzu) if not small else 12
        created_malz = 0
        for row in malzeme_havuzu[:target_malz]:
            isim, kategori, marka, birim, kdv, kmin, kmax = row
            kritik = Decimal(str(rng.randrange(kmin, kmax + 1)))
            _, created = Malzeme.objects.get_or_create(
                isim=isim,
                defaults={
                    "kategori": kategori,
                    "marka": marka,
                    "birim": birim,
                    "kdv_orani": kdv,
                    "kritik_stok": kritik,
                    "aciklama": "Demo malzeme (otomatik üretildi)",
                },
            )
            if created:
                created_malz += 1
        self.stdout.write(f" - Malzemeler tamam: +{created_malz}")

        self.stdout.write(self.style.SUCCESS("✅ DEMO VERİLER OLUŞTURULDU."))

    def _reset_demo_tables(self):
        """
        Seed öncesi sadece seed'in bastığı tabloları temizler.
        (Kullanıcılar ve finans hareketleri vs. burada yok.)
        """
        self.stdout.write(self.style.WARNING("🧹 --reset verildi: demo tablolar temizleniyor..."))
        # FK bağımlılığı: Malzeme/IsKalemi -> Kategori gibi olabilir, önce çocukları sil
        for model, label in [
            (Malzeme, "Malzeme"),
            (IsKalemi, "IsKalemi"),
            (Depo, "Depo"),
            (Tedarikci, "Tedarikci"),
            (Kategori, "Kategori"),
        ]:
            try:
                c = model.objects.count()
                model.objects.all().delete()
                self.stdout.write(f" - {label} silindi: {c}")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f" ! {label} silinemedi: {e}"))
