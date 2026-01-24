from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Count
from core.models import Fatura, SatinAlma
from core.forms import FaturaGirisForm, SerbestFaturaGirisForm, FaturaKalemFormSet
from core.services import InvoiceService
from core.decorators import yetki_kontrol

@login_required
def fatura_girisi(request, siparis_id):
    """
    SENARYO 1: Siparişe İstinaden Fatura
    Kullanıcı sadece başlık girer, kalemler SİPARİŞTEN OTOMATİK oluşur.
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)
    
    # Eğer hizmet/taşeron siparişi ise hizmet faturasına yönlendir
    if getattr(siparis.teklif, "is_kalemi", None):
        return redirect('hizmet_faturasi_giris', siparis_id=siparis.id)

    if request.method == "POST":
        form = FaturaGirisForm(request.POST, request.FILES)
        
        if form.is_valid():
            try:
                fatura = form.save(commit=False)
                # Servis, siparişteki bilgileri alıp kalemleri yaratacak
                InvoiceService.fatura_olustur_siparisten(fatura, siparis)
                
                messages.success(request, f"✅ Fatura siparişten otomatik oluşturuldu. Toplam: {fatura.genel_toplam}")
                return redirect('islem_sonuc', model_name='fatura', pk=fatura.id)
            except Exception as e:
                messages.error(request, f"⛔ Hata: {str(e)}")
        else:
            messages.error(request, "⛔ Form bilgilerini kontrol ediniz.")
    else:
        form = FaturaGirisForm(initial={"tarih": timezone.now().date()})

    return render(request, "fatura_girisi.html", {
        "siparis": siparis, 
        "form": form,
    })

@login_required
def serbest_fatura_girisi(request):
    """
    SENARYO 2: Serbest Fatura (Manuel)
    Tedarikçi seçilir, kalemler elle girilir.
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    if request.method == "POST":
        form = SerbestFaturaGirisForm(request.POST, request.FILES)
        formset = FaturaKalemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            try:
                fatura = form.save(commit=False)
                # Formdan seçilen depoyu al
                depo_id = form.cleaned_data.get('depo').id if form.cleaned_data.get('depo') else None
                
                InvoiceService.fatura_kaydet_manuel(fatura, formset, depo_id=depo_id)

                messages.success(request, f"✅ Serbest fatura kaydedildi.")
                return redirect('islem_sonuc', model_name='fatura', pk=fatura.id)
            except Exception as e:
                messages.error(request, f"⛔ Hata: {str(e)}")
        else:
            messages.error(request, f"⛔ Form hatalı: {form.errors} {formset.errors}")
    else:
        form = SerbestFaturaGirisForm(initial={"tarih": timezone.now().date()})
        formset = FaturaKalemFormSet()

    return render(request, "serbest_fatura_girisi.html", {
        "form": form, 
        "formset": formset,
        "is_serbest": True 
    })

@login_required
def hizmet_faturasi_giris(request, siparis_id):
    """
    Hizmet Faturaları için
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)

    if request.method == 'POST':
        form = FaturaGirisForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                fatura = form.save(commit=False)
                InvoiceService.fatura_olustur_siparisten(fatura, siparis)
                
                messages.success(request, "✅ Hizmet faturası işlendi.")
                return redirect('islem_sonuc', model_name='fatura', pk=fatura.id)
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = FaturaGirisForm(initial={"tarih": timezone.now().date()})

    return render(request, 'hizmet_faturasi.html', {
        'siparis': siparis,
        'form': form
    })

@login_required
def fatura_listesi(request):
    """
    Sisteme kayıtlı faturaların listelendiği ekran.
    ÖZELLİK: Tarih filtresi ve Finansal Özet Kartları eklendi.
    DÜZELTME: Veritabanı tip hataları (Decimal/Float) Python tarafında 'or 0' ile çözüldü.
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI', 'OFIS_VE_SATINALMA']):
        return redirect('erisim_engellendi')

    # 1. Filtre Parametrelerini Al
    baslangic = request.GET.get('baslangic')
    bitis = request.GET.get('bitis')
    
    # 2. Temel Sorgu
    faturalar = Fatura.objects.all().select_related('tedarikci').order_by('-tarih', '-created_at')

    # 3. Tarih Filtresi Uygula
    if baslangic:
        faturalar = faturalar.filter(tarih__gte=baslangic)
    if bitis:
        faturalar = faturalar.filter(tarih__lte=bitis)

    # 4. Özet Hesaplamaları (GÜVENLİ YÖNTEM)
    # Coalesce kullanmadan, ham veriyi alıp Python'da 0'a çeviriyoruz.
    # Bu yöntem veritabanı backend'inden bağımsız çalışır ve tip hatası vermez.
    ham_ozet = faturalar.aggregate(
        toplam_tutar=Sum('genel_toplam'),
        toplam_kdv=Sum('kdv_toplam'),
        toplam_matrah=Sum('ara_toplam'),
        adet=Count('id')
    )

    ozet = {
        'toplam_tutar': ham_ozet['toplam_tutar'] or 0,
        'toplam_kdv': ham_ozet['toplam_kdv'] or 0,
        'toplam_matrah': ham_ozet['toplam_matrah'] or 0,
        'adet': ham_ozet['adet']
    }

    context = {
        'faturalar': faturalar,
        'ozet': ozet,
        'filtre': {
            'baslangic': baslangic, 
            'bitis': bitis
        }
    }
    
    return render(request, 'fatura_listesi.html', context)