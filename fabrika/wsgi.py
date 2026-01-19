import os

from django.core.wsgi import get_wsgi_application

# Burası da 'fabrika.settings' olmalı
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fabrika.settings')

application = get_wsgi_application()