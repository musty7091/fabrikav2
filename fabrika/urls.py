from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

# Genel Viewlar
from core import views

# Parçalanmış Finans Modülleri
from core.views import finans_invoices, finans_payments
from core.views.ekstre import stok_ekstresi, cari_ekstresi

urlpatterns = [
    path('admin/', admin.site.urls),

    # 1. Ana Karşılama ve Güvenlik
    path('', views.dashboard, name='dashboard'),
    path('erisim-engellendi/', views.erisim_engellendi, name='erisim_engellendi'),
    path('cikis/', views.cikis_yap, name='cikis_yap'),

    # 2. İcmal & Raporlama
    path('icmal/', views.icmal_raporu, name='icmal_raporu'),
    path('arsiv/', views.arsiv_raporu, name='arsiv_raporu'),

    # 3. Dashboardlar
    path('finans-dashboard/', finans_payments.finans_dashboard, name='finans_dashboard'),
    path('odeme-dashboard/', finans_payments.odeme_dashboard, name='odeme_dashboard'),
    path('depo-dashboard/', views.depo_dashboard, name='depo_dashboard'),

    # 4. Fatura Sistemi (finans_invoices)
    path('finans/faturalar/', finans_invoices.fatura_listesi, name='fatura_listesi'),
    path("finans/fatura/<int:siparis_id>/", finans_invoices.fatura_girisi, name="fatura_girisi"),
    path("fatura/serbest/", finans_invoices.serbest_fatura_girisi, name="serbest_fatura_girisi"),
    path('fatura/hizmet/<int:siparis_id>/', finans_invoices.hizmet_faturasi_giris, name='hizmet_faturasi_giris'),
    path('fatura/sil/<int:fatura_id>/', views.fatura_sil, name='fatura_sil'),

    # 5. Ödeme ve Hakediş Sistemi (finans_payments)
    path('hakedis/ekle/<int:siparis_id>/', finans_payments.hakedis_ekle, name='hakedis_ekle'),
    path('odeme/yap/', finans_payments.odeme_yap, name='odeme_yap'),
    path('cek-takibi/', finans_payments.cek_takibi, name='cek_takibi'),
    path('cek-durum/<int:odeme_id>/', finans_payments.cek_durum_degistir, name='cek_durum_degistir'),
    path("finans/avans-mahsup/<int:tedarikci_id>/", finans_payments.avans_mahsup, name="avans_mahsup"),
    path('finans/detay-ozet/', finans_payments.finans_ozeti, name='finans_ozeti'),

    # 6. Talep & Teklif Yönetimi
    path('talep/yeni/', views.talep_olustur, name='talep_olustur'),
    path('talep/onayla/<int:talep_id>/', views.talep_onayla, name='talep_onayla'),
    path('talep/tamamla/<int:talep_id>/', views.talep_tamamla, name='talep_tamamla'),
    path('talep/sil/<int:talep_id>/', views.talep_sil, name='talep_sil'),
    path('talep/geri-al/<int:talep_id>/', views.talep_arsivden_cikar, name='talep_arsivden_cikar'),
    path('teklif/ekle/', views.teklif_ekle, name='teklif_ekle'),
    path('teklif/durum/<int:teklif_id>/<str:yeni_durum>/', views.teklif_durum_guncelle, name='teklif_durum_guncelle'),

    # 7. Sipariş & Mal Kabul
    path('siparisler/', views.siparis_listesi, name='siparis_listesi'),
    path('siparis/detay/<int:siparis_id>/', views.siparis_detay, name='siparis_detay'),
    path('mal-kabul/<int:siparis_id>/', views.mal_kabul, name='mal_kabul'),

    # 8. Stok & Depo Yönetimi
    path('stok-listesi/', views.stok_listesi, name='stok_listesi'),
    path('stok/gecmis/<int:malzeme_id>/', views.stok_hareketleri, name='stok_hareketleri'),
    path('depo/transfer/', views.depo_transfer, name='depo_transfer'),
    path('rapor/envanter/', views.envanter_raporu, name='envanter_raporu'),

    # 9. Giderler (OPEX)
    path("giderler/", views.gider_listesi, name="gider_listesi"),
    path("gider/ekle/", views.gider_ekle, name="gider_ekle"),
    path("gider/<int:pk>/duzenle/", views.gider_duzenle, name="gider_duzenle"),
    path("tanimlar/gider/", views.gider_tanim_listesi, name="gider_tanim_listesi"),
    path("tanimlar/gider/ekle/", views.gider_tanim_ekle, name="gider_tanim_ekle"),
    path("tanimlar/gider/<int:pk>/duzenle/", views.gider_tanim_duzenle, name="gider_tanim_duzenle"),
    path("tanimlar/gider/<int:pk>/toggle/", views.gider_tanim_toggle_active, name="gider_tanim_toggle_active"),

    # 10. Tanımlamalar (Master Data)
    path('tanim-yonetimi/', views.tanim_yonetimi, name='tanim_yonetimi'),
    path('tedarikciler/', views.tedarikci_listesi, name='tedarikci_listesi'),
    path('tedarikci/ekle/', views.tedarikci_ekle, name='tedarikci_ekle'),
    path('tedarikci/duzenle/<int:pk>/', views.tedarikci_duzenle, name='tedarikci_duzenle'),
    path('tedarikci/sil/<int:pk>/', views.tedarikci_sil, name='tedarikci_sil'),

    path('depolar/', views.depo_listesi, name='depo_listesi'),
    path('depo/ekle/', views.depo_ekle, name='depo_ekle'),
    path('depo/duzenle/<int:pk>/', views.depo_duzenle, name='depo_duzenle'),
    path('depo/sil/<int:pk>/', views.depo_sil, name='depo_sil'),

    path('malzeme/ekle/', views.malzeme_ekle, name='malzeme_ekle'),
    path('malzeme/duzenle/<int:pk>/', views.malzeme_duzenle, name='malzeme_duzenle'),
    path('malzeme/sil/<int:pk>/', views.malzeme_sil, name='malzeme_sil'),

    path('hizmet-listesi/', views.hizmet_listesi, name='hizmet_listesi'),
    path('hizmet/ekle/', views.hizmet_ekle, name='hizmet_ekle'),
    path('hizmet/duzenle/<int:pk>/', views.hizmet_duzenle, name='hizmet_duzenle'),
    path('hizmet/sil/<int:pk>/', views.hizmet_sil, name='hizmet_sil'),

    path('kategoriler/', views.kategori_listesi, name='kategori_listesi'),
    path('kategori/ekle/', views.kategori_ekle, name='kategori_ekle'),
    path('kategori/duzenle/<int:pk>/', views.kategori_duzenle, name='kategori_duzenle'),
    path('kategori/sil/<int:pk>/', views.kategori_sil, name='kategori_sil'),
    path('tanim/toggle/<str:model>/<int:pk>/', views.tanim_toggle_active, name='tanim_toggle_active'),

    # 11. Ekstreler & API
    path("ekstre/stok/", stok_ekstresi, name="stok_ekstresi"),
    path("ekstre/cari/", cari_ekstresi, name="cari_ekstresi"),
    path('api/kur/', views.kur_getir, name='kur_getir'),
    path('api/tedarikci-bakiye/<int:tedarikci_id>/', views.get_tedarikci_bakiye, name='api_tedarikci_bakiye'),
    path('api/depo-stok/', views.get_depo_stok, name='get_depo_stok'),

    # 12. Yardımcılar
    path('islem-sonuc/<str:model_name>/<int:pk>/', views.islem_sonuc, name='islem_sonuc'),
    path('yazdir/<str:model_name>/<int:pk>/', views.belge_yazdir, name='belge_yazdir'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)