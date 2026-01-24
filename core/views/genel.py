from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.utils import timezone
from django.db.models import Sum, F
from decimal import Decimal
from datetime import date
from django.core.exceptions import ObjectDoesNotExist

# --- MODELLERİN EKSİKSİZ IMPORT EDİLMESİ ---
from core.models import (
    MalzemeTalep, Teklif, Odeme, Harcama, 
    SatinAlma, Fatura, Malzeme, Hakedis, Depo, Tedarikci, DepoTransfer, DepoHareket
)
from .guvenlik import yetki_kontrol
from core.utils import to_decimal, tcmb_kur_getir

def erisim_engellendi(request):
    return render(request, 'erisim_engellendi.html')

@login_required
def dashboard(request):
    """
    Ana Dashboard (Operasyonel Özet)
    """
    bekleyen_talep = MalzemeTalep.objects.filter(durum='bekliyor').count()
    bekleyen_siparis = SatinAlma.objects.exclude(teslimat_durumu='tamamlandi').count()
    
    # Fatura modeli durum alanı olmadığı için matematiksel filtre
    acik_fatura_sayisi = Fatura.objects.filter(odenen_tutar__lt=F('genel_toplam')).count()
    
    kritik_stok_sayisi = 0
    try:
        for m in Malzeme.objects.filter(kritik_stok__gt=0):
            if m.stok <= m.kritik_stok:
                kritik_stok_sayisi += 1
    except:
        pass

    context = {
        'bekleyen_talep_sayisi': bekleyen_talep,
        'bekleyen_siparisler': bekleyen_siparis,
        'onay_bekleyen_faturalar': acik_fatura_sayisi,
        'kritik_stok': kritik_stok_sayisi,
    }
    return render(request, 'dashboard.html', context)

@login_required
def finans_dashboard(request):
    """
    Tüm finansal hesaplamalar artık finans_payments.py dosyasındaki 
    odeme_dashboard fonksiyonunda (TL Bazlı) yapılmaktadır.
    """
    return redirect('odeme_dashboard')

@login_required
def islem_sonuc(request, model_name, pk):
    """
    İşlem başarılı olduktan sonra "Yazdırılsın mı?" sorusunu soran ara ekran.
    Hayıra basınca ilgili listeye yönlendirir.
    """
    context = {
        'model_name': model_name,
        'pk': pk,
    }

    # "Hayır" denildiğinde dönülecek URL'yi belirle
    if model_name == 'depotransfer':
        # Envanter sayfasına dön
        context['return_url'] = 'stok_listesi' 
        
    elif model_name == 'fatura':
        # Fatura listesine dön
        context['return_url'] = 'fatura_listesi'
        
    elif model_name == 'odeme':
        # Finans paneline dön
        context['return_url'] = 'odeme_dashboard'
        
    elif model_name == 'harcama':
        # Gider listesine dön
        context['return_url'] = 'gider_listesi'
        
    elif model_name == 'tedarikci':
        # Tedarikçi listesine dön
        context['return_url'] = 'tedarikci_listesi'
        
    else:
        # Varsayılan dashboard
        context['return_url'] = 'dashboard'

    return render(request, 'islem_sonuc.html', context)

# core/views/genel.py dosyasındaki belge_yazdir fonksiyonunu bununla değiştirin:

@login_required
def belge_yazdir(request, model_name, pk):
    """
    GENEL BELGE YAZDIRMA MODÜLÜ (GENİŞLETİLMİŞ)
    Tüm operasyonel belgeler için A4 çıktı üretir.
    """
    context = {}
    
    if model_name == 'satinalma':
        obj = get_object_or_404(SatinAlma, pk=pk)
        context = {
            'belge': obj, 'model_name': 'satinalma',
            'baslik': "SATINALMA SİPARİŞ FORMU",
            'kod': f"SIP-{obj.id:04d}", 'tarih': obj.siparis_tarihi
        }
        
    elif model_name == 'hakedis':
        obj = get_object_or_404(Hakedis, pk=pk)
        context = {
            'belge': obj, 'model_name': 'hakedis',
            'baslik': "HAKEDİŞ RAPORU & ÖDEME EMRİ",
            'kod': f"HKD-{obj.hakedis_no}", 'tarih': obj.tarih
        }
        
    elif model_name == 'odeme':
        obj = get_object_or_404(Odeme, pk=pk)
        turu = obj.get_odeme_turu_display().upper()
        context = {
            'belge': obj, 'model_name': 'odeme',
            'baslik': f"TEDİYE MAKBUZU ({turu})",
            'kod': f"ODM-{obj.id:04d}", 'tarih': obj.tarih
        }
        
    elif model_name == 'fatura':
        obj = get_object_or_404(Fatura, pk=pk)
        context = {
            'belge': obj, 'model_name': 'fatura',
            'baslik': "FATURA GİRİŞ FİŞİ",
            'kod': f"FTR-{obj.fatura_no}", 'tarih': obj.tarih
        }

    # --- YENİ EKLENENLER ---

    elif model_name == 'depotransfer':
        obj = get_object_or_404(DepoTransfer, pk=pk)
        context = {
            'belge': obj, 'model_name': 'depotransfer',
            'baslik': "DEPO SEVK / TRANSFER İRSALİYESİ",
            'kod': f"TRF-{obj.id:04d}", 'tarih': obj.tarih
        }

    elif model_name == 'harcama':
        obj = get_object_or_404(Harcama, pk=pk)
        context = {
            'belge': obj, 'model_name': 'harcama',
            'baslik': "GİDER / MASRAF MAKBUZU",
            'kod': f"EXP-{obj.id:04d}", 'tarih': obj.tarih
        }
    
    elif model_name == 'depohareket':
        obj = get_object_or_404(DepoHareket, pk=pk)
        tur = obj.get_islem_turu_display().upper()
        context = {
            'belge': obj, 'model_name': 'depohareket',
            'baslik': f"STOK HAREKET FİŞİ ({tur})",
            'kod': f"STK-{obj.id:04d}", 'tarih': obj.tarih
        }

    elif model_name == 'tedarikci':
        # Cari Mutabakat Formu (Snapshot)
        obj = get_object_or_404(Tedarikci, pk=pk)
        
        # Basit Bakiye Hesabı (Fatura+Hakediş - Ödeme)
        t_fat = obj.faturalar.aggregate(t=Sum('genel_toplam'))['t'] or 0
        t_ode = obj.odemeler.aggregate(t=Sum('tutar'))['t'] or 0
        
        # Hakediş toplama (biraz dolaylı)
        t_hak = 0
        for teklif in obj.teklifler.all():
            if hasattr(teklif, 'satinalma_donusumu'):
                for h in teklif.satinalma_donusumu.hakedisler.filter(onay_durumu=True):
                    t_hak += (h.brut_tutar + h.kdv_tutari)
        
        bakiye = (float(t_fat) + float(t_hak)) - float(t_ode)

        context = {
            'belge': obj, 'model_name': 'tedarikci',
            'baslik': "CARİ HESAP MUTABAKAT MEKTUBU",
            'kod': f"MUT-{obj.id:04d}", 'tarih': timezone.now(),
            'ekstra': {'bakiye': bakiye, 'borc': float(t_fat)+float(t_hak), 'alacak': float(t_ode)}
        }

    else:
        return render(request, 'erisim_engellendi.html', {'mesaj': 'Geçersiz belge türü.'})

    return render(request, 'belge_yazdir.html', context)

def cikis_yap(request):
    logout(request)
    return redirect('/admin/login/')