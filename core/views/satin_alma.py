from decimal import Decimal, ROUND_HALF_UP
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from core.models import SatinAlma, Depo, DepoHareket, Fatura, DepoTransfer
from core.forms import FaturaGirisForm
from .guvenlik import yetki_kontrol
from core.utils import to_decimal
from django.db.models import F


@login_required
def siparis_listesi(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')
    
    # KRİTİK FİLTRE: Sadece teklifi 'onaylandi' durumunda olan siparişleri getiriyoruz
    tum_siparisler = SatinAlma.objects.filter(
        teklif__durum='onaylandi'
    ).select_related(
        'teklif__tedarikci', 'teklif__malzeme', 'teklif__is_kalemi'
    ).prefetch_related('depo_hareketleri', 'depo_hareketleri__depo').order_by('-created_at')

    bekleyenler, bitenler = [], []
    for siparis in tum_siparisler:
        # Sanal depoda mal varsa veya fatura kesilmemiş miktar varsa işlem bitmemiştir.
        if siparis.sanal_depoda_bekleyen > 0 or siparis.kalan_fatura_miktar > 0:
            bekleyenler.append(siparis)
        else:
            bitenler.append(siparis)

    return render(request, 'siparis_listesi.html', {
        'bekleyenler': bekleyenler,
        'bitenler': bitenler
    })

@login_required
def mal_kabul(request):
    """
    Mal Kabul Sayfası: Sadece 'onaylandi' durumundaki tekliflere ait
    ve sanal depoda sevkiyat bekleyen ürünleri listeler.
    """
    if not yetki_kontrol(request.user, ['SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')
    
    # KRİTİK FİLTRE: Sadece onaylı teklifler
    siparisler = SatinAlma.objects.filter(
        teklif__durum='onaylandi'
    ).select_related('teklif__tedarikci', 'teklif__malzeme').order_by('-created_at')
    
    # Sadece sanal depoda stoğu olanları göster
    aktif_siparisler = [s for s in siparisler if s.sanal_depoda_bekleyen > 0]
    
    fiziksel_depolar = Depo.objects.filter(is_sanal=False)
    
    return render(request, 'mal_kabul.html', {
        'siparisler': aktif_siparisler,
        'depolar': fiziksel_depolar
    })

def fatura_girisi(request, siparis_id=None):
    """
    Fatura Girildiğinde Stok OTOMATİK OLARAK 'Sanal Depo'ya girer.
    Hesaplama yapılırken Teklifin KDV Dahil olup olmadığı kontrol edilir.
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    # URL'den veya query'den ID'yi al (Sizin orijinal kontrolünüzü korudum)
    s_id = siparis_id or request.GET.get('siparis_id')
    secili_siparis = None
    if s_id:
        secili_siparis = get_object_or_404(SatinAlma, id=s_id)

    sanal_depo = Depo.objects.filter(is_sanal=True).first()

    if request.method == 'POST':
        form = FaturaGirisForm(request.POST, request.FILES)
        if form.is_valid():
            fatura = form.save(commit=False)
            fatura.satinalma = secili_siparis
            fatura.kayit_eden = request.user
            fatura.save()
            
            # F() Kullanımı: Yarış durumunu (Lost Update) önlemek için
            SatinAlma.objects.filter(id=secili_siparis.id).update(
                faturalanan_miktar=F('faturalanan_miktar') + fatura.miktar
            )

            # Sanal depoya giriş hareketi
            DepoHareket.objects.create(
                siparis=secili_siparis,
                depo=fatura.depo, 
                malzeme=secili_siparis.teklif.malzeme,
                miktar=fatura.miktar,
                islem_turu='giris', 
                aciklama=f"{fatura.fatura_no} nolu fatura ile sanal stok girişi"
            )

            messages.success(request, f"✅ Fatura kaydedildi ve {fatura.miktar} birim sanal stoğa eklendi.")
            return redirect('siparis_listesi')
    else:
        # Sizin orijinal miktar/tutar otomatik doldurma mantığınız:
        initial_data = {}
        if sanal_depo:
            initial_data['depo'] = sanal_depo.id
            
        if secili_siparis:
            teklif = secili_siparis.teklif
            miktar = secili_siparis.kalan_fatura_miktar
            birim_fiyat = teklif.birim_fiyat
            
            # Matrah (KDV'siz tutar) hesapla
            tutar_hesaplanan = birim_fiyat * miktar
            
            # Eğer teklif KDV HARİÇ ise KDV oranını üzerine ekle
            if not teklif.kdv_dahil_mi:
                kdv_orani = Decimal(str(teklif.kdv_orani))
                tutar_hesaplanan = tutar_hesaplanan * (1 + (kdv_orani / 100))
            
            initial_data['miktar'] = miktar
            initial_data['tutar'] = tutar_hesaplanan.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
        form = FaturaGirisForm(initial=initial_data)

    return render(request, 'fatura_girisi.html', {
        'form': form,
        'secili_siparis': secili_siparis,
        'sanal_depo': sanal_depo
    })

@login_required
def mal_kabul_islem(request, siparis_id):
    """
    GÜNCEL AKIŞ: Manuel stok hareketi yerine DepoTransfer kullanır.
    Böylece çift kayıt ve yanlış field (hareket_turu) hataları önlenir.
    """
    if not yetki_kontrol(request.user, ['SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')
        
    siparis = get_object_or_404(SatinAlma, id=siparis_id)
    fiziksel_depolar = Depo.objects.filter(is_sanal=False)
    
    if request.method == 'POST':
        miktar = to_decimal(request.POST.get('miktar'))
        hedef_depo_id = request.POST.get('depo')
        hedef_depo = get_object_or_404(Depo, id=hedef_depo_id)
        
        if miktar > siparis.sanal_depoda_bekleyen:
            messages.error(request, f"Hata: Sanal depoda sadece {siparis.sanal_depoda_bekleyen} birim mal var!")
            return redirect('mal_kabul')

        sanal_depo = Depo.objects.filter(is_sanal=True).first()
        
        # ✅ TEK YOL: Manuel DepoHareket yerine Transfer oluşturuyoruz.
        # Bu işlem core/signals.py üzerinden merkezi olarak yönetilir.
        DepoTransfer.objects.create(
            malzeme=siparis.teklif.malzeme,
            miktar=miktar,
            kaynak_depo=sanal_depo,
            hedef_depo=hedef_depo,
            bagli_siparis=siparis,
            tarih=timezone.now().date(),
            notlar=f"Satın alma mal kabulü: {siparis.id}"
        )

        # Teslim edilen miktarı güvenli şekilde (F() ile) artırıyoruz
        SatinAlma.objects.filter(id=siparis.id).update(
            teslim_edilen=F('teslim_edilen') + miktar
        )

        messages.success(request, f"✅ {miktar} birim mal başarıyla {hedef_depo.isim} deposuna alındı.")
        return redirect('mal_kabul')

    return render(request, 'mal_kabul_islem.html', {'siparis': siparis, 'depolar': fiziksel_depolar})

@login_required
def siparis_detay(request, siparis_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')
    siparis = get_object_or_404(SatinAlma, id=siparis_id)
    hareketler = DepoHareket.objects.filter(siparis=siparis).order_by('-tarih')
    faturalar = siparis.faturalar.all().order_by('-tarih')
    
    return render(request, 'siparis_detay.html', {
        'siparis': siparis, 
        'hareketler': hareketler,
        'faturalar': faturalar
    })

@login_required
def fatura_sil(request, fatura_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')
    
    fatura = get_object_or_404(Fatura, id=fatura_id)
    siparis = fatura.satinalma
    
    # F() ile güvenli miktar güncelleme
    SatinAlma.objects.filter(id=siparis.id).update(
        faturalanan_miktar=F('faturalanan_miktar') - fatura.miktar
    )
    
    # Faturaya bağlı DepoHareket kaydını bul ve sil
    DepoHareket.objects.filter(
        siparis=siparis, 
        miktar=fatura.miktar, 
        islem_turu='giris',
        aciklama__icontains=fatura.fatura_no
    ).delete()
    
    fatura.delete()
    messages.warning(request, f"🗑️ {fatura.fatura_no} nolu fatura ve ilgili stok girişi silindi.")
    return redirect('siparis_detay', siparis_id=siparis.id)