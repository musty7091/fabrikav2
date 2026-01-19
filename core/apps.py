from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Sinyalleri (Signals) import ederek devreye alıyoruz
        import core.signals