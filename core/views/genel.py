from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.utils import timezone
from core.models import MalzemeTalep, Teklif, Odeme, Harcama
from .guvenlik import yetki_kontrol

def erisim_engellendi(request):
    return render(request, 'erisim_engellendi.html')

@login_required
def dashboard(request):
    bekleyen_talep_sayisi = MalzemeTalep.objects.filter(durum='bekliyor').count()
    context = {'bekleyen_talep_sayisi': bekleyen_talep_sayisi}
    return render(request, 'dashboard.html', context)

@login_required
def islem_sonuc(request, model_name, pk):
    return render(request, 'islem_sonuc.html', {'model_name': model_name, 'pk': pk})

@login_required
def belge_yazdir(request, model_name, pk):
    belge_data = {}
    baslik = ""
    
    def hesapla_bakiye(tedarikci):
        if not tedarikci: return 0
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
        ilgili_is = f"Hakediş #{obj.bagli_hakedis.hakedis_no}" if obj.bagli_hakedis else "Genel / Mahsuben (Cari Hesaba)"
            
        belge_data = {
            'İşlem No': f"OD-{obj.id}",
            'İşlem Tarihi': obj.tarih,
            'Yazdırılma Zamanı': timezone.now(),
            'Kime Ödendi': obj.tedarikci.firma_unvani,
            'İlgili İş / Hakediş': ilgili_is,
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