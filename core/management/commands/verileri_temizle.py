from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import connection

class Command(BaseCommand):
    help = 'Kullanıcılar hariç core uygulamasındaki tüm verileri temizler'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING("⚠️ Tüm veriler (Kullanıcılar hariç) siliniyor..."))
        
        # Core uygulamasındaki tüm modelleri al
        core_models = apps.get_app_config('core').get_models()
        
        # İlişkisel veri tabanlarında (PostgreSQL, MySQL, SQLite) 
        # Foreign Key hataları almamak için kısıtlamaları geçici olarak kapatıyoruz
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute('PRAGMA foreign_keys = OFF;')
            elif connection.vendor == 'postgresql':
                cursor.execute('SET CONSTRAINTS ALL DEFERRED;')
            else:
                cursor.execute('SET FOREIGN_KEY_CHECKS = 0;')

            for model in core_models:
                # Kullanıcı modelini asla silme (User modeli genelde django.contrib.auth içindedir ama önlem olarak)
                if model.__name__ in ['User', 'UserProfile']: 
                    continue
                
                count = model.objects.all().count()
                if count > 0:
                    model.objects.all().delete()
                    self.stdout.write(f"- {model.__name__}: {count} kayıt silindi.")

            # Kısıtlamaları tekrar aç
            if connection.vendor == 'sqlite':
                cursor.execute('PRAGMA foreign_keys = ON;')
            elif connection.vendor == 'postgresql':
                pass # Postgres otomatik geri açar
            else:
                cursor.execute('SET FOREIGN_KEY_CHECKS = 1;')

        self.stdout.write(self.style.SUCCESS('✅ Envanter, stoklar ve tüm raporlar başarıyla temizlendi.'))