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
    # 1. Bekleyen Talepler
    bekleyen_talep = MalzemeTalep.objects.filter(durum='bekliyor').count()
    
    # 2. Tamamlanmamış Siparişler
    # Modelde alan adı 'teslimat_durumu' olduğu için düzeltildi.
    bekleyen_siparis = SatinAlma.objects.exclude(teslimat_durumu='tamamlandi').count()
    
    # 3. Ödenmemiş Faturalar
    # Fatura modelinde 'durum' alanı yok. Bu yüzden (Ödenen < Genel Toplam) mantığı kuruldu.
    acik_fatura_sayisi = Fatura.objects.filter(odenen_tutar__lt=F('genel_toplam')).count()
    
    # 4. Kritik Stok Sayısı
    # Stok property olduğu için Python tarafında sayıyoruz
    kritik_stok_sayisi = 0
    try:
        # Performans için kritik stok tanımlı olanları çekip kontrol edelim
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
    FİNANS KOKPİTİ (NİHAİ VERSİYON)
    Borçları TL, USD, EUR olarak ayrı ayrı hesaplar ve gösterir.
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    # --- 1. Borçları Para Birimine Göre Hesapla ---
    borc_listesi = {} # {'TL': 1000, 'USD': 500}

    # A) Açık Faturalar (Ödenen < Genel Toplam)
    acik_faturalar = Fatura.objects.filter(odenen_tutar__lt=F('genel_toplam'))
    
    for fat in acik_faturalar:
        # Para birimi tespiti (Güvenli)
        curr = 'TL'
        try:
            if fat.satinalma and fat.satinalma.teklif:
                curr = fat.satinalma.teklif.para_birimi
        except ObjectDoesNotExist:
            pass # Varsayılan TL kalır

        # Kalan tutarı hesapla
        # En garantisi veritabanındaki Odeme tablosunu toplamaktır
        odenen_db = Odeme.objects.filter(fatura=fat).aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0')
        odenen_field = to_decimal(fat.odenen_tutar)
        
        # Hangisi güncelse onu al
        mevcut_odenen = max(odenen_db, odenen_field)
        
        kalan = to_decimal(fat.genel_toplam) - to_decimal(mevcut_odenen)
        
        if kalan > 0.1:
            if curr not in borc_listesi:
                borc_listesi[curr] = Decimal('0')
            borc_listesi[curr] += kalan

    # B) Onaylı Hakedişler
    acik_hakedisler = Hakedis.objects.filter(onay_durumu=True)
    
    for hk in acik_hakedisler:
        curr = 'TL'
        try:
            if hk.satinalma and hk.satinalma.teklif:
                curr = hk.satinalma.teklif.para_birimi
        except ObjectDoesNotExist:
            pass
            
        kalan = to_decimal(hk.odenecek_net_tutar) - to_decimal(hk.fiili_odenen_tutar)
        
        if kalan > 0.1:
            if curr not in borc_listesi:
                borc_listesi[curr] = Decimal('0')
            borc_listesi[curr] += kalan

    # --- 2. Diğer İstatistikler ---
    toplam_odeme_bu_ay = Odeme.objects.filter(
        tarih__month=date.today().month,
        tarih__year=date.today().year
    ).aggregate(toplam=Sum('tutar'))['toplam'] or 0

    son_odemeler = Odeme.objects.all().order_by('-tarih')[:6]
    
    # Bekleyen faturaları vade tarihine göre çek
    bekleyen_faturalar = Fatura.objects.filter(odenen_tutar__lt=F('genel_toplam')).order_by('tarih')[:6]

    context = {
        'borc_listesi': borc_listesi, 
        'toplam_odeme_bu_ay': toplam_odeme_bu_ay,
        'son_odemeler': son_odemeler,
        'bekleyen_faturalar': bekleyen_faturalar,
        'kurlar': tcmb_kur_getir(),
    }
    return render(request, 'finans_dashboard.html', context)

@login_required
def islem_sonuc(request, model_name, pk):
    return render(request, 'islem_sonuc.html', {'model_name': model_name, 'pk': pk})

@login_required
def belge_yazdir(request, model_name, pk):
    belge_data = {}
    baslik = ""
    
    def hesapla_bakiye(tedarikci):
        if not tedarikci: return 0
        # Basit bakiye hesabı
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
            'Birim Fiyat (KDV Hariç)': f"{obj.birim_fiyat:,.2f} {obj.para_birimi}",
            'KDV Oranı': f"%{obj.kdv_orani}",
            'Birim Fiyat (KDV Dahil)': f"{obj.birim_fiyat_kdvli:,.2f} {obj.para_birimi}",
            'Kur': f"{obj.kur_degeri}",
            'Toplam Maliyet (TL)': f"{obj.toplam_fiyat_tl:,.2f} TL",
            'Durum': obj.get_durum_display(),
            '------------------': '------------------', 
            'Güncel Firma Bakiyesi': f"{bakiye:,.2f} TL"
        }
    elif model_name == 'odeme':
        obj = get_object_or_404(Odeme, pk=pk)
        baslik = "TEDARİKÇİ ÖDEME MAKBUZU"
        detay = f"({obj.get_odeme_turu_display()})"
        if obj.odeme_turu == 'cek': detay += f" - Vade: {obj.vade_tarihi}"
        bakiye = hesapla_bakiye(obj.tedarikci)
        
        ilgili_is = "Genel / Mahsuben"
        if obj.bagli_hakedis:
            ilgili_is = f"Hakediş #{obj.bagli_hakedis.hakedis_no}"
        elif obj.fatura: # Modeli güncellediğimiz için artık bu alan var
            ilgili_is = f"Fatura #{obj.fatura.fatura_no}"
            
        belge_data = {
            'İşlem No': f"OD-{obj.id}",
            'İşlem Tarihi': obj.tarih,
            'Yazdırılma Zamanı': timezone.now(),
            'Kime Ödendi': obj.tedarikci.firma_unvani,
            'İlgili İş / Evrak': ilgili_is,
            'Ödeme Tutarı': f"{obj.tutar:,.2f} {obj.para_birimi}",
            'Ödeme Yöntemi': detay,
            'Açıklama': obj.aciklama,
            '------------------': '------------------',
            'Kalan Borç Bakiyesi': f"{bakiye:,.2f} TL"
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
        onay_zamani = obj.onay_tarihi.strftime('%d.%m.%Y %H:%M') if obj.onay_tarihi else "- (Bekliyor)"
        temin_zamani = obj.temin_tarihi.strftime('%d.%m.%Y %H:%M') if obj.temin_tarihi else "- (Bekliyor)"
        talep_eden_bilgi = f"{obj.talep_eden.first_name} {obj.talep_eden.last_name} ({obj.talep_eden.username})" if obj.talep_eden else "Bilinmiyor"

        belge_data = {
            'Talep No': f"TLP-{obj.id:04d}",
            'Talep Oluşturulma': talep_zamani,
            'Talep Eden': talep_eden_bilgi,
            '------------------': '------------------',
            'İstenen Malzeme': obj.malzeme.isim if obj.malzeme else obj.is_kalemi.isim,
            'Miktar': f"{obj.miktar}",
            'Kullanılacak Yer': obj.proje_yeri,
            'Aciliyet Durumu': obj.get_oncelik_display(),
            'Açıklama / Not': obj.aciklama,
            '-------------------': '------------------',
            'DURUM': obj.get_durum_display(),
            '🕒 Onaylanma Zamanı': onay_zamani,
            '🚚 Temin/Teslim Zamanı': temin_zamani,
        }

    context = {'baslik': baslik, 'data': belge_data, 'tarih_saat': timezone.now()}
    return render(request, 'belge_yazdir.html', context)

def cikis_yap(request):
    logout(request)
    return redirect('/admin/login/')