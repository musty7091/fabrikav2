from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from core.models import Malzeme, MalzemeTalep, DepoHareket, Teklif, Tedarikci, Odeme, Harcama, IsKalemi

class Command(BaseCommand):
    help = 'Otomatik olarak kullanıcı gruplarını ve yetkilerini oluşturur.'

    def handle(self, *args, **kwargs):
        # 1. GRUPLARI OLUŞTUR
        # ---------------------------------------------------------
        saha_group, created_saha = Group.objects.get_or_create(name='SAHA_EKIBI')
        ofis_group, created_ofis = Group.objects.get_or_create(name='OFIS_VE_SATINALMA')
        finans_group, created_finans = Group.objects.get_or_create(name='MUHASEBE_FINANS')

        self.stdout.write("✅ Gruplar kontrol edildi/oluşturuldu.")

        # 2. İZİNLERİ TANIMLA (MODEL BAZLI)
        # ---------------------------------------------------------
        
        # Yardımcı Fonksiyon: İzinleri Modele Göre Bul
        def get_perms(model_class, perms_list):
            content_type = ContentType.objects.get_for_model(model_class)
            return Permission.objects.filter(content_type=content_type, codename__in=perms_list)

        # A. SAHA EKİBİ YETKİLERİ
        # Sadece talep açabilsin, malzeme listesini ve kendi depo hareketlerini görsün.
        saha_perms = []
        saha_perms.extend(get_perms(MalzemeTalep, ['add_malzemetalep', 'view_malzemetalep']))
        saha_perms.extend(get_perms(DepoHareket, ['add_depohareket', 'view_depohareket']))
        saha_perms.extend(get_perms(Malzeme, ['view_malzeme']))
        saha_group.permissions.set(saha_perms)
        self.stdout.write(f"👷 SAHA_EKIBI yetkileri atandı ({len(saha_perms)} izin).")

        # B. OFİS VE SATINALMA YETKİLERİ
        # Teklif, Tedarikçi, Malzeme yönetimi tam yetki. Ödemeleri sadece görsün.
        ofis_perms = []
        # Tam Yetkiler (Ekle/Düzenle/Sil/Gör)
        for model in [Teklif, Tedarikci, Malzeme, MalzemeTalep, DepoHareket, IsKalemi]:
            ct = ContentType.objects.get_for_model(model)
            ofis_perms.extend(Permission.objects.filter(content_type=ct))
        
        # Kısıtlı Yetkiler (Sadece Gör)
        ofis_perms.extend(get_perms(Odeme, ['view_odeme']))
        
        ofis_group.permissions.set(ofis_perms)
        self.stdout.write(f"💼 OFIS_VE_SATINALMA yetkileri atandı ({len(ofis_perms)} izin).")

        # C. MUHASEBE VE FİNANS YETKİLERİ
        # Ödeme, Çek, Gider yönetimi tam yetki. Diğerlerini görsün.
        finans_perms = []
        # Tam Yetkiler
        for model in [Odeme, Harcama]:
            ct = ContentType.objects.get_for_model(model)
            finans_perms.extend(Permission.objects.filter(content_type=ct))
            
        # Görme Yetkileri (İcmal ve Tedarikçileri görmesi lazım)
        finans_perms.extend(get_perms(Teklif, ['view_teklif']))
        finans_perms.extend(get_perms(Tedarikci, ['view_tedarikci']))
        
        finans_group.permissions.set(finans_perms)
        self.stdout.write(f"💰 MUHASEBE_FINANS yetkileri atandı ({len(finans_perms)} izin).")

        self.stdout.write(self.style.SUCCESS('\n🚀 KURULUM TAMAMLANDI! Gruplar ve yetkiler hazir.'))