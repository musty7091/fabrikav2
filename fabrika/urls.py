from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from core import views 

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 1. Ana Karşılama
    path('', views.dashboard, name='dashboard'),
    path('erisim-engellendi/', views.erisim_engellendi, name='erisim_engellendi'),

    # 2. Modüller (İcmal & Teklif)
    path('icmal/', views.icmal_raporu, name='icmal_raporu'),
    path('teklif/ekle/', views.teklif_ekle, name='teklif_ekle'),
    
    # 3. Dashboardlar
    path('finans-dashboard/', views.finans_dashboard, name='finans_dashboard'),
    path('depo-dashboard/', views.depo_dashboard, name='depo_dashboard'),
    path('odeme-dashboard/', views.odeme_dashboard, name='odeme_dashboard'),
    
    # 4. Detaylar
    path('finans/detay-ozet/', views.finans_ozeti, name='finans_ozeti'),
    path('cek-takibi/', views.cek_takibi, name='cek_takibi'),
    
    # 5. İşlemler (Finans & Teklif)
    path('cek-durum/<int:odeme_id>/', views.cek_durum_degistir, name='cek_durum_degistir'),
    path('tedarikci/<int:tedarikci_id>/', views.tedarikci_ekstresi, name='tedarikci_ekstresi'),
    path('teklif/durum/<int:teklif_id>/<str:yeni_durum>/', views.teklif_durum_guncelle, name='teklif_durum_guncelle'),
    path('fatura/hizmet/<int:siparis_id>/', views.finans.hizmet_faturasi_giris, name='hizmet_faturasi_giris'),
    
    # 6. Hızlı Tanımlamalar (Popup/Yeni Sekme)
    path('tedarikci/ekle/', views.tedarikci_ekle, name='tedarikci_ekle'),
    path('malzeme/ekle/', views.malzeme_ekle, name='malzeme_ekle'),
    
    # 7. Talep Yönetimi (YENİ EKLENENLER)
    path('talep/yeni/', views.talep_olustur, name='talep_olustur'),
    path('talep/onayla/<int:talep_id>/', views.talep_onayla, name='talep_onayla'),
    path('talep/tamamla/<int:talep_id>/', views.talep_tamamla, name='talep_tamamla'),
    path('talep/sil/<int:talep_id>/', views.talep_sil, name='talep_sil'),
    path('arsiv/', views.arsiv_raporu, name='arsiv_raporu'),
    path('talep/geri-al/<int:talep_id>/', views.talep_arsivden_cikar, name='talep_arsivden_cikar'),
    path('stok-listesi/', views.stok_listesi, name='stok_listesi'),
    path('hizmet-listesi/', views.hizmet_listesi, name='hizmet_listesi'),
    path('hizmet/ekle/', views.hizmet_ekle, name='hizmet_ekle'),
    path('hizmet/duzenle/<int:pk>/', views.hizmet_duzenle, name='hizmet_duzenle'),
    path('hizmet/sil/<int:pk>/', views.hizmet_sil, name='hizmet_sil'),
    path('siparisler/', views.siparis_listesi, name='siparis_listesi'),
    path('mal-kabul/<int:siparis_id>/', views.mal_kabul, name='mal_kabul'),
    path('siparis/detay/<int:siparis_id>/', views.siparis_detay, name='siparis_detay'),
    path('fatura-gir/<int:siparis_id>/', views.fatura_girisi, name='fatura_girisi'),
    path('fatura/sil/<int:fatura_id>/', views.fatura_sil, name='fatura_sil'),
    path('depo/transfer/', views.depo_transfer, name='depo_transfer'),
    path('api/depo-stok/', views.get_depo_stok, name='get_depo_stok'),
    path('debug/stok/<int:malzeme_id>/', views.stok_rontgen),
    path('stok/gecmis/<int:malzeme_id>/', views.stok_hareketleri, name='stok_hareketleri'),
    path('rapor/envanter/', views.envanter_raporu, name='envanter_raporu'),
    path('hakedis/ekle/<int:siparis_id>/', views.hakedis_ekle, name='hakedis_ekle'),
    path('odeme/yap/', views.odeme_yap, name='odeme_yap'),
    path('cari/ekstre/<int:tedarikci_id>/', views.cari_ekstre, name='cari_ekstre'),
    path('tanim-yonetimi/', views.tanim_yonetimi, name='tanim_yonetimi'),
    path('kategori/ekle/', views.kategori_ekle, name='kategori_ekle'),
    path('depo/ekle/', views.depo_ekle, name='depo_ekle'),
    path('kategoriler/', views.kategori_listesi, name='kategori_listesi'),
    path('kategori/duzenle/<int:pk>/', views.kategori_duzenle, name='kategori_duzenle'),
    path('kategori/sil/<int:pk>/', views.kategori_sil, name='kategori_sil'),
    path('depolar/', views.depo_listesi, name='depo_listesi'),
    path('depo/duzenle/<int:pk>/', views.depo_duzenle, name='depo_duzenle'),
    path('depo/sil/<int:pk>/', views.depo_sil, name='depo_sil'),
    path('tedarikciler/', views.tedarikci_listesi, name='tedarikci_listesi'),
    path('tedarikci/duzenle/<int:pk>/', views.tedarikci_duzenle, name='tedarikci_duzenle'),
    path('tedarikci/sil/<int:pk>/', views.tedarikci_sil, name='tedarikci_sil'),
    path('malzeme/duzenle/<int:pk>/', views.malzeme_duzenle, name='malzeme_duzenle'),
    path('malzeme/sil/<int:pk>/', views.malzeme_sil, name='malzeme_sil'),
    path('islem-sonuc/<str:model_name>/<int:pk>/', views.islem_sonuc, name='islem_sonuc'),
    path('yazdir/<str:model_name>/<int:pk>/', views.belge_yazdir, name='belge_yazdir'),
    path('api/tedarikci-bakiye/<int:tedarikci_id>/', views.get_tedarikci_bakiye, name='api_tedarikci_bakiye'),
    
    # 9. Oturum
    path('cikis/', views.cikis_yap, name='cikis_yap'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)