"""
Django settings for fabrika project.
"""
from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-change-this-key-for-production'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = [
    'https://*.ngrok-free.app',
]

# Application definition
INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core.apps.CoreConfig',
    'django.contrib.humanize',  # Sizin uygulamanız burada
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'fabrika.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # DIRS KISMI KRİTİK OLAN YERDİR:
        'DIRS': [os.path.join(BASE_DIR, 'core/templates')], 
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'fabrika.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db_v2.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'tr-tr'
USE_I18N = True
USE_TZ = True

# ÖNEMLİ: Manuel ayarların baskın gelmesi için bunu FALSE yapmalısın
USE_L10N = False 

USE_THOUSAND_SEPARATOR = True
NUMBER_GROUPING = 3

# Türkiye Standartları
THOUSAND_SEPARATOR = '.'   # Binlik ayraç NOKTA
DECIMAL_SEPARATOR = ','    # Ondalık ayraç VİRGÜL

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

# Bu satır çok önemli: Django'ya "Ekstra dosyalarım burada" diyoruz
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Media Files (Yüklenen PDF'ler için)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --- JAZZMIN AYARLARI ---

JAZZMIN_SETTINGS = {
    # Site başlığı
    "site_title": "AECO Fabrika Proje Yönetimi",
    "site_header": "AECO Fabrika Maliyet Sistemi",
    "site_brand": "AECO Fabrika",
    "welcome_sign": "Proje Yönetim Paneline Hoşgeldiniz",
    "copyright": "AECO Trading Ltd.",

    # Siteye Dönüş Butonları
    "topmenu_links": [
        # Ana Sayfaya (Dashboard) Dönüş Butonu
        {"name": "Ana Sayfa",  "url": "/", "permissions": ["auth.view_user"]},
        
        # Direkt İcmal Listesine Gidiş Butonu
        {"name": "İcmal Listesi", "url": "/icmal/"},
    ],
    
    # Menülerin açılır/kapanır olması için
    "navigation_expanded": True,
    
    # İkonlar (Bootstrap ikon isimleri)
    "icons": {
        "core.Kategori": "fas fa-layer-group",
        "core.Tedarikci": "fas fa-handshake",
        "core.IsKalemi": "fas fa-tasks",
        "core.Teklif": "fas fa-file-invoice-dollar",
    },
}

# Tema rengi (Cerulean, Cosby, Flatly, Darkly vb. seçebilirsiniz)
JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    
    # Burası CSS dosyasını sisteme yükler
    "css": {
        "all": ["css/admin_button.css"]
    }
}

# --- GİRİŞ / ÇIKIŞ YÖNLENDİRMELERİ ---
# Giriş yapılmamışsa kullanıcıyı Admin giriş paneline yönlendir
LOGIN_URL = '/admin/login/'

# Giriş yaptıktan sonra tekrar anasayfaya (Dashboard) gönder
LOGIN_REDIRECT_URL = '/'

# Çıkış yapınca tekrar giriş sayfasına dön
LOGOUT_REDIRECT_URL = '/admin/login/'

# ==========================================
# OTURUM (SESSION) AYARLARI - ÇIKIŞ SORUNU İÇİN
# ==========================================

# Oturum süresi: 30 gün (Saniye cinsinden: 60 * 60 * 24 * 30)
SESSION_COOKIE_AGE = 2592000

# Tarayıcıyı kapatınca oturum kapanmasın (False yaptık)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Her işlemde süreyi sıfırla (Böylece aktif kullanıcı atılmaz)
SESSION_SAVE_EVERY_REQUEST = True