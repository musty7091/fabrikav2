"""
Django settings for fabrika project (fabrikav2).

Hedef:
- Localde: DEBUG=1 ile rahat geliştirme
- Prod'a geçince: sadece .env değiştir, kod aynı kalsın
- SECRET_KEY / ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS env ile yönetilsin
"""

from pathlib import Path
import os

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------
# .env yükleme (python-dotenv varsa)
# ------------------------------------------------------------
try:
    from dotenv import load_dotenv  # pip install python-dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    # dotenv yoksa bile proje çalışsın; env değişkenleri yine OS'ten okunur.
    pass


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default).strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


# ------------------------------------------------------------
# Core security
# ------------------------------------------------------------
# Localde .env ile set et. Prod'a geçince mutlaka .env'den gelsin.
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "p@f#61x1%i@dm2p@)f1bs11$g2xhbt2w*-yq9!qnade=")

# Local test için default açık (DJANGO_DEBUG=1)
DEBUG = env_bool("DJANGO_DEBUG", True)

# Local default: sadece localhost
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")

# Ngrok / prod domainleri buraya:
# DJANGO_CSRF_TRUSTED_ORIGINS=https://*.ngrok-free.app,https://site.com
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")
# Localde ngrok kullanıyorsan rahat et diye:
if DEBUG and not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = ["https://*.ngrok-free.app"]


# ------------------------------------------------------------
# Application definition
# ------------------------------------------------------------
INSTALLED_APPS = [
    "jazzmin",

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "django.contrib.humanize",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fabrika.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Senin mevcut yapın: core/templates içinden yükle
        "DIRS": [os.path.join(BASE_DIR, "core", "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "fabrika.wsgi.application"


# ------------------------------------------------------------
# Database (v2: db_v2.sqlite3)
# İstersen .env ile değiştirebilirsin:
# DJANGO_DB_PATH=C:\fabrikav2\db_v2.sqlite3
# ------------------------------------------------------------
db_path = os.getenv("DJANGO_DB_PATH", str(BASE_DIR / "db_v2.sqlite3"))

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": db_path,
    }
}


# ------------------------------------------------------------
# Password validation
# ------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ------------------------------------------------------------
# Internationalization
# ------------------------------------------------------------
LANGUAGE_CODE = "tr-tr"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Europe/Istanbul")

USE_I18N = True
USE_TZ = True

# Manuel TR sayı formatları
USE_L10N = False
USE_THOUSAND_SEPARATOR = True
NUMBER_GROUPING = 3
THOUSAND_SEPARATOR = "."
DECIMAL_SEPARATOR = ","


# ------------------------------------------------------------
# Static files
# ------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]

# Prod için topla (collectstatic) klasörü (istersen)
STATIC_ROOT = os.getenv("DJANGO_STATIC_ROOT", "") or None


# ------------------------------------------------------------
# Media files
# ------------------------------------------------------------
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")


# ------------------------------------------------------------
# Default primary key field type
# ------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ------------------------------------------------------------
# Jazzmin
# ------------------------------------------------------------
JAZZMIN_SETTINGS = {
    "site_title": "AECO Fabrika Proje Yönetimi",
    "site_header": "AECO Fabrika Maliyet Sistemi",
    "site_brand": "AECO Fabrika",
    "welcome_sign": "Proje Yönetim Paneline Hoşgeldiniz",
    "copyright": "AECO Trading Ltd.",

    "topmenu_links": [
        {"name": "Ana Sayfa", "url": "/", "permissions": ["auth.view_user"]},
        {"name": "İcmal Listesi", "url": "/icmal/"},
    ],

    "navigation_expanded": True,

    "icons": {
        "core.Kategori": "fas fa-layer-group",
        "core.Tedarikci": "fas fa-handshake",
        "core.IsKalemi": "fas fa-tasks",
        "core.Teklif": "fas fa-file-invoice-dollar",
    },
}

JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    "css": {"all": ["css/admin_button.css"]},
}


# ------------------------------------------------------------
# Login/Logout redirects
# ------------------------------------------------------------
LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/admin/login/"


# ------------------------------------------------------------
# Session settings (çıkış sorunu için)
# ------------------------------------------------------------
SESSION_COOKIE_AGE = int(os.getenv("DJANGO_SESSION_COOKIE_AGE", "2592000"))  # 30 gün
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE", False)
SESSION_SAVE_EVERY_REQUEST = env_bool("DJANGO_SESSION_SAVE_EVERY_REQUEST", True)


# ------------------------------------------------------------
# Security hardening (prod'da devreye girecek şekilde)
# ------------------------------------------------------------
# Prod'da .env ile aç:
# DJANGO_SECURE_SSL_REDIRECT=1
# DJANGO_SESSION_COOKIE_SECURE=1
# DJANGO_CSRF_COOKIE_SECURE=1
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", False)
