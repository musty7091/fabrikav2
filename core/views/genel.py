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
    SatinAlma, Fatura, Malzeme, Hakedis, Depo, Tedarikci
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
    return render(request, 'islem_sonuc.html', {'model_name': model_name, 'pk': pk})

@login_required
def belge_yazdir(request, model_name, pk):
    belge_data = {}
    baslik = ""
    
    # Basit bakiye
    def hesapla_bakiye(tedarikci):
        if not tedarikci: return 0
        # Burada sadece kabaca hesaplıyoruz, detaylısı ekstrede
        borc = sum(t.toplam_fiyat_tl for t in tedarikci.teklifler.filter(durum='onaylandi'))
        odenen = float(sum(o.tutar for o in tedarikci.odemeler.all()))
        return borc - odenen

    if model_name == 'teklif':
        obj = get_object_or_404(Teklif, pk=pk)
        baslik = "SATIN ALMA / TEKLİF FİŞİ"
        bakiye = hesapla_bakiye(obj.tedarikci)
        is_adi = obj.malzeme.isim if obj.malzeme else (obj.is_kalemi.isim if obj.is_kalemi else "Belirtilmemiş")

        belge_data = {
            'İşlem No': f"TK-{obj.id}",
            'Tarih': timezone.now(), 
            'Firma': obj.tedarikci.firma_unvani,
            'İş Kalemi / Malzeme': is_adi,
            'Miktar': f"{obj.miktar}",
            'Birim Fiyat': f"{obj.birim_fiyat:,.2f} {obj.para_birimi}",
            'Toplam Maliyet': f"{obj.toplam_fiyat_tl:,.2f} TL",
            'Durum': obj.get_durum_display(),
            'Güncel Firma Bakiyesi': f"{bakiye:,.2f} TL"
        }
    elif model_name == 'odeme':
        obj = get_object_or_404(Odeme, pk=pk)
        baslik = "TEDARİKÇİ ÖDEME MAKBUZU"
        bakiye = hesapla_bakiye(obj.tedarikci)
        detay = f"({obj.get_odeme_turu_display()})"
        if obj.odeme_turu == 'cek': detay += f" - Vade: {obj.vade_tarihi}"
        
        ilgili_is = "Genel / Mahsuben"
        if obj.bagli_hakedis:
            ilgili_is = f"Hakediş #{obj.bagli_hakedis.hakedis_no}"
        elif obj.fatura:
            ilgili_is = f"Fatura #{obj.fatura.fatura_no}"

        belge_data = {
            'İşlem No': f"OD-{obj.id}",
            'Tarih': obj.tarih,
            'Kime': obj.tedarikci.firma_unvani,
            'İlgili İş': ilgili_is,
            'Tutar': f"{obj.tutar:,.2f} {obj.para_birimi}",
            'Tür': detay,
            'Açıklama': obj.aciklama,
            'Kalan Bakiye': f"{bakiye:,.2f} TL"
        }
    elif model_name == 'harcama':
        obj = get_object_or_404(Harcama, pk=pk)
        baslik = "GİDER / HARCAMA FİŞİ"
        belge_data = {
            'İşlem No': f"HR-{obj.id}",
            'Tarih': obj.tarih,
            'Kategori': obj.kategori.isim,
            'Açıklama': obj.aciklama,
            'Tutar': f"{obj.tutar:,.2f} {obj.para_birimi}",
        }
    elif model_name == 'malzemetalep':
        obj = get_object_or_404(MalzemeTalep, pk=pk)
        baslik = "MALZEME TALEP VE TAKİP FORMU"
        talep_zamani = obj.tarih.strftime('%d.%m.%Y %H:%M')
        
        is_adi = "Belirtilmemiş"
        if obj.malzeme: is_adi = obj.malzeme.isim
        elif obj.is_kalemi: is_adi = obj.is_kalemi.isim

        talep_eden = "Bilinmiyor"
        if obj.talep_eden:
            talep_eden = f"{obj.talep_eden.first_name} {obj.talep_eden.last_name}"

        belge_data = {
            'Talep No': f"TLP-{obj.id:04d}",
            'Talep Oluşturulma': talep_zamani,
            'Talep Eden': talep_eden,
            'İstenen Malzeme': is_adi,
            'Miktar': f"{obj.miktar}",
            'Kullanılacak Yer': obj.proje_yeri,
            'Aciliyet': obj.get_oncelik_display(),
            'Durum': obj.get_durum_display(),
        }

    context = {'baslik': baslik, 'data': belge_data, 'tarih_saat': timezone.now()}
    return render(request, 'belge_yazdir.html', context)

def cikis_yap(request):
    logout(request)
    return redirect('/admin/login/')