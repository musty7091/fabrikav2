# core/views/finans_invoices.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from core.models import SatinAlma, Depo, Fatura
# Formlar (İsim düzeltildi)
from core.forms import FaturaGirisForm, SerbestFaturaGirisForm, FaturaKalemFormSet
# Servis
from core.services.finans_invoices import InvoiceService
# Güvenlik
from core.views.guvenlik import yetki_kontrol

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
        # Eski SiparisFaturaForm yerine artık FaturaGirisForm kullanıyoruz
        form = FaturaGirisForm(request.POST, request.FILES)
        
        if form.is_valid():
            try:
                fatura = form.save(commit=False)
                # Servis, siparişteki bilgileri alıp kalemleri yaratacak
                InvoiceService.fatura_olustur_siparisten(fatura, siparis)
                
                messages.success(request, f"✅ Fatura siparişten otomatik oluşturuldu. Toplam: {fatura.genel_toplam}")
                return redirect("siparis_listesi")
            except Exception as e:
                messages.error(request, f"⛔ Hata: {str(e)}")
        else:
            messages.error(request, "⛔ Form bilgilerini kontrol ediniz.")
    else:
        # Formun boş hali
        form = FaturaGirisForm(initial={"tarih": timezone.now().date()})

    return render(request, "fatura_girisi.html", {
        "siparis": siparis, 
        "form": form,
        # 'formset' göndermiyoruz, böylece template'de tablo çıkmayacak
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
                return redirect("serbest_fatura_girisi")
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
                return redirect('siparis_listesi')
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = FaturaGirisForm(initial={"tarih": timezone.now().date()})

    return render(request, 'hizmet_faturasi.html', {
        'siparis': siparis,
        'form': form
    })