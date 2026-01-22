# core/views/__init__.py

# Genel yardımcılar (cikis_yap BURADAN gelmeli)
from .genel import (
    dashboard, erisim_engellendi, islem_sonuc, 
    belge_yazdir, cikis_yap
)

# Modüller
from .satin_alma import (
    siparis_listesi, siparis_detay, mal_kabul, fatura_sil
)

from .talep_teklif import (
    icmal_raporu, teklif_ekle, teklif_durum_guncelle,
    talep_olustur, talep_onayla, talep_tamamla, talep_sil,
    arsiv_raporu, talep_arsivden_cikar
)

from .tanimlar import (
    tanim_toggle_active,
    tanim_yonetimi,
    kategori_ekle, kategori_listesi, kategori_duzenle, kategori_sil,
    depo_ekle, depo_listesi, depo_duzenle, depo_sil,
    tedarikci_ekle, tedarikci_listesi, tedarikci_duzenle, tedarikci_sil,
    malzeme_ekle, malzeme_duzenle, malzeme_sil,
    hizmet_listesi, hizmet_ekle, hizmet_duzenle, hizmet_sil
)

from .stok_depo import (
    depo_dashboard, stok_listesi, depo_transfer,
    stok_hareketleri, get_depo_stok, stok_rontgen, envanter_raporu
)

# Finans Ödeme ve Faturalar (urls.py'de direkt import edildiği için buraya zorunlu değil
# ama views.get_tedarikci_bakiye gibi kullanımlar için ekliyoruz)
try:
    from .finans_payments import get_tedarikci_bakiye
except ImportError:
    pass

# Ekstreler
from .ekstre import stok_ekstresi, cari_ekstresi

# Güvenlik (yetki_kontrol BURADA)
from .guvenlik import yetki_kontrol