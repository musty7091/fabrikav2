from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.apps import apps

# Asla dokunma (kullanıcı ve Django sistem tabloları)
PROTECTED_TABLE_PREFIXES = (
    "auth_",
    "django_",
)

# Ek koruma: bazı projelerde user modeli "users_user" gibi olabilir.
# Buraya kendi user tablonu da ekleyebilirsin ama auth_user ise zaten auth_ ile korunuyor.
PROTECTED_TABLE_EXACT = {
    # "users_user",
}

class Command(BaseCommand):
    help = "Kullanıcılar hariç tüm tablo verilerini siler (DEV için toplu sıfırlama)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-sessions",
            action="store_true",
            help="django_session tablosunu da temizle (default: HAYIR).",
        )
        parser.add_argument(
            "--include-adminlog",
            action="store_true",
            help="django_admin_log tablosunu da temizle (default: HAYIR).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        vendor = connection.vendor  # 'postgresql', 'sqlite', 'mysql', 'oracle'
        include_sessions = options["include_sessions"]
        include_adminlog = options["include_adminlog"]

        tables = self._get_all_tables()

        # Korunanları ayıkla
        to_clear = []
        for t in tables:
            if self._is_protected_table(t, include_sessions, include_adminlog):
                continue
            to_clear.append(t)

        if not to_clear:
            self.stdout.write(self.style.WARNING("Temizlenecek tablo bulunamadı."))
            return

        self.stdout.write(self.style.WARNING("⚠️ DİKKAT: Bu işlem geri alınamaz (DEV için)."))
        self.stdout.write(f"DB: {vendor} | Temizlenecek tablo sayısı: {len(to_clear)}")

        if vendor == "postgresql":
            self._truncate_postgres(to_clear)
        elif vendor == "sqlite":
            self._clear_sqlite(to_clear)
        elif vendor == "mysql":
            self._truncate_mysql(to_clear)
        else:
            # Oracle vb. için güvenli fallback: model bazlı delete
            self._fallback_model_delete()

        self.stdout.write(self.style.SUCCESS("✅ Veritabanı (kullanıcılar hariç) temizlendi."))

    def _get_all_tables(self):
        # Django’nun bildiği tüm tablolar
        return list(connection.introspection.table_names())

    def _is_protected_table(self, table_name: str, include_sessions: bool, include_adminlog: bool) -> bool:
        if table_name in PROTECTED_TABLE_EXACT:
            return True

        # Prefix koruma
        if table_name.startswith(PROTECTED_TABLE_PREFIXES):
            # opsiyonlarla bazı django_* tablolarını temizleyebilirsin
            if include_sessions and table_name == "django_session":
                return False
            if include_adminlog and table_name == "django_admin_log":
                return False
            return True

        return False

    def _truncate_postgres(self, tables):
        with connection.cursor() as cursor:
            # quote_name ile güvenli hale getiriyoruz
            qtables = ", ".join(connection.ops.quote_name(t) for t in tables)
            cursor.execute(f"TRUNCATE TABLE {qtables} RESTART IDENTITY CASCADE;")
        self.stdout.write(f" - PostgreSQL truncate OK: {len(tables)} tablo")

    def _clear_sqlite(self, tables):
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA foreign_keys = OFF;")
            for t in tables:
                cursor.execute(f"DELETE FROM {connection.ops.quote_name(t)};")
            # AUTOINCREMENT sayaçlarını sıfırla
            try:
                cursor.execute("DELETE FROM sqlite_sequence;")
            except Exception:
                pass
            cursor.execute("PRAGMA foreign_keys = ON;")
        self.stdout.write(f" - SQLite delete OK: {len(tables)} tablo")

    def _truncate_mysql(self, tables):
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
            for t in tables:
                cursor.execute(f"TRUNCATE TABLE {connection.ops.quote_name(t)};")
            cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
        self.stdout.write(f" - MySQL truncate OK: {len(tables)} tablo")

    def _fallback_model_delete(self):
        """
        Çok nadir DB'lerde: auth/django app'lerini dışarıda bırakıp,
        kalan tüm modelleri delete eder.
        """
        excluded_apps = {"auth", "admin", "contenttypes", "sessions"}
        models = [m for m in apps.get_models() if m._meta.app_label not in excluded_apps]
        # FK sırası için tersine basit yaklaşım: büyükten küçüğe silmeye çalışırız.
        # Dev ortamda genelde yeterli.
        for m in reversed(models):
            try:
                c = m.objects.count()
                if c:
                    m.objects.all().delete()
                    self.stdout.write(f" - {m._meta.label} silindi: {c}")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f" ! {m._meta.label} silinemedi: {e}"))
