# core/views/__init__.py
"""
Bu dosya, urls.py'nin `from core import views` kullanımını desteklemek için
alt modüllerdeki view fonksiyonlarını buraya "export" eder.

urls.py içinde views.xxx şeklinde çağrılan her fonksiyonun burada görünür olması gerekir.
"""

# Genel / Dashboard
from .genel import *      # dashboard, erisim_engellendi vb.

# Finans
from .finans import *     # finans_dashboard, odeme_dashboard, cek_takibi, cek_durum_degistir, ...

# Satın Alma / Sipariş / Fatura
from .satin_alma import * # siparis_listesi, mal_kabul, fatura_girisi, fatura_sil, depo_transfer vb.

# Stok / Depo
from .stok_depo import *  # depo_dashboard, stok_listesi vb.

# Talep / Teklif
from .talep_teklif import *  # talep_olustur, teklif_ekle, teklif_durum_guncelle vb.

# Tanımlar
from .tanimlar import *   # kategori_ekle, depo_ekle, tedarikci_ekle vb.

# Ekstre modülü (ekstre.py içinde ayrıca fonksiyonlar varsa)
from .ekstre import *     # stok_ekstresi, cari_ekstresi vb. (varsa)
