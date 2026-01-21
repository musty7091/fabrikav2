# core/views/finans_payments.py
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum
from django.http import JsonResponse

# Modeller ve Formlar
from core.models import (
    SatinAlma, Hakedis, Odeme, Tedarikci, FaturaKalem, 
    Kategori, GiderKategorisi, Teklif, Fatura  # Fatura eklendi
)
from core.forms import HakedisForm, OdemeForm
from core.views.guvenlik import yetki_kontrol
from core.utils import to_decimal, tcmb_kur_getir

# Servis
from core.services.finans_payments import PaymentService


@login_required
def hakedis_ekle(request, siparis_id):
    # Bu fonksiyon değişmedi
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    siparis = get_object_or_404(SatinAlma, id=siparis_id)
    mevcut_toplam = Hakedis.objects.filter(satinalma=siparis).aggregate(t=Sum('tamamlanma_orani'))['t'] or Decimal('0.00')
    kalan_kapasite = (Decimal('100.00') - to_decimal(mevcut_toplam))

    if request.method == 'POST':
        form = HakedisForm(request.POST)
        if form.is_valid():
            hakedis = form.save(commit=False)
            hakedis.satinalma = siparis
            hakedis.onay_durumu = True
            try:
                PaymentService.hakedis_validasyon(siparis.id, hakedis.tamamlanma_orani)
                hakedis.save()
                PaymentService.siparis_guncelle(siparis, hakedis.tamamlanma_orani)
                messages.success(request, f"✅ %{hakedis.tamamlanma_orani} hakediş onaylandı.")
                return redirect('siparis_listesi')
            except Exception as e:
                messages.error(request, f"Hata: {str(e)}")
    else:
        form = HakedisForm(initial={
            'tarih': timezone.now().date(),
            'hakedis_no': Hakedis.objects.filter(satinalma=siparis).count() + 1,
        })

    return render(request, 'hakedis_ekle.html', {
        'form': form, 'siparis': siparis, 'mevcut_toplam': mevcut_toplam, 'kalan_kapasite': kalan_kapasite
    })


@login_required
def odeme_yap(request):
    """
    YENİ MANTIK: Borçlar = Onaylı Hakedişler + Kayıtlı Faturalar
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    tedarikci_id = request.GET.get('tedarikci_id') or request.POST.get('tedarikci')
    acik_kalemler = []
    secilen_tedarikci = None
    toplam_borc = Decimal('0.00')

    if tedarikci_id:
        try:
            secilen_tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)

            # 1. Hakedişlerden Doğan Borçlar
            hakedisler = Hakedis.objects.filter(
                satinalma__teklif__tedarikci=secilen_tedarikci,
                onay_durumu=True
            )
            for hk in hakedisler:
                kalan = to_decimal(hk.odenecek_net_tutar) - to_decimal(hk.fiili_odenen_tutar)
                if kalan > 0.1: 
                    acik_kalemler.append({
                        'id': hk.id, 'tip': 'Hakedis', 
                        'tarih': hk.tarih,
                        'aciklama': f"Hakediş #{hk.hakedis_no} - {hk.satinalma.teklif.is_kalemi.isim}",
                        'tutar': hk.odenecek_net_tutar,
                        'kalan': kalan
                    })

            # 2. Faturalardan Doğan Borçlar
            faturalar = Fatura.objects.filter(tedarikci=secilen_tedarikci).order_by('tarih')
            
            for fat in faturalar:
                # odenen_tutar alanı modelde olmalı
                mevcut_odenen = getattr(fat, 'odenen_tutar', Decimal('0'))
                kalan = to_decimal(fat.genel_toplam) - mevcut_odenen
                
                if kalan > 0.1:
                    acik_kalemler.append({
                        'id': fat.id, 'tip': 'Fatura',
                        'tarih': fat.tarih,
                        'aciklama': f"Fatura #{fat.fatura_no} ({fat.aciklama or ''})",
                        'tutar': fat.genel_toplam,
                        'kalan': kalan 
                    })
            
            # Toplam Borç Hesabı
            toplam_borc = sum(k['kalan'] for k in acik_kalemler)

        except Exception as e:
            messages.error(request, f"Hata: {str(e)}")

    if request.method == 'POST':
        form = OdemeForm(request.POST)
        if form.is_valid():
            try:
                odeme = form.save(commit=False)
                odeme.save()
                
                # SEÇİLENLERİ KAPAT
                secilenler = request.POST.getlist('secilen_kalem')
                dagitilacak = odeme.tutar
                
                for secim in secilenler:
                    if dagitilacak <= 0: break
                    
                    tip, id_str = secim.split('_')
                    obj_id = int(id_str)
                    
                    if tip == 'Hakedis':
                        hk = Hakedis.objects.get(id=obj_id)
                        borc = to_decimal(hk.odenecek_net_tutar) - to_decimal(hk.fiili_odenen_tutar)
                        odenecek = min(dagitilacak, borc)
                        hk.fiili_odenen_tutar = to_decimal(hk.fiili_odenen_tutar) + odenecek
                        hk.save()
                        dagitilacak -= odenecek
                        
                    elif tip == 'Fatura':
                        fat = Fatura.objects.get(id=obj_id)
                        mevcut_odenen = getattr(fat, 'odenen_tutar', Decimal('0'))
                        borc = to_decimal(fat.genel_toplam) - mevcut_odenen
                        odenecek = min(dagitilacak, borc)
                        fat.odenen_tutar = mevcut_odenen + odenecek
                        fat.save()
                        dagitilacak -= odenecek

                messages.success(request, f"✅ {odeme.tutar} {odeme.para_birimi} ödeme kaydedildi.")
                return redirect(f"/odeme/yap/?tedarikci_id={odeme.tedarikci.id}")
            except Exception as e:
                messages.error(request, f"Kayıt hatası: {str(e)}")
    else:
        form = OdemeForm(initial={'tarih': timezone.now().date(), 'tedarikci': secilen_tedarikci})

    return render(request, 'odeme_yap.html', {
        'form': form,
        'tedarikciler': Tedarikci.objects.all(),
        'secilen_tedarikci': secilen_tedarikci,
        'acik_kalemler': acik_kalemler,
        'toplam_borc': toplam_borc
    })


@login_required
def finans_dashboard(request):
    """
    YENİ MANTIK: Fatura ve Hakediş toplamları
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    # 1. Borçlar
    toplam_fatura_borcu = Fatura.objects.aggregate(t=Sum('genel_toplam'))['t'] or Decimal('0')
    toplam_hakedis_borcu = Hakedis.objects.filter(onay_durumu=True).aggregate(t=Sum('odenecek_net_tutar'))['t'] or Decimal('0')
    
    toplam_borc = toplam_fatura_borcu + toplam_hakedis_borcu
    
    # 2. Ödemeler
    toplam_odenen = Odeme.objects.aggregate(t=Sum('tutar'))['t'] or Decimal('0')
    
    # 3. Kalan
    kalan_borc = toplam_borc - toplam_odenen

    # 4. Giderler
    harcama_tutari = Decimal('0.00')
    gider_labels, gider_data = [], []
    for gk in GiderKategorisi.objects.all():
        tutar = sum(to_decimal(h.tl_tutar) for h in gk.harcamalar.all())
        if tutar > 0:
            gider_labels.append(gk.isim)
            gider_data.append(float(tutar))
            harcama_tutari += tutar

    context = {
        'genel_toplam': toplam_borc, 
        'harcama_tutari': harcama_tutari,
        'kalan_borc': kalan_borc,
        'gider_labels': gider_labels,
        'gider_data': gider_data,
        'kurlar': tcmb_kur_getir(),
    }
    return render(request, 'finans_dashboard.html', context)


@login_required
def cari_ekstre(request, tedarikci_id):
    # YENİ MANTIK: Fatura listeleme
    tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
    hareketler = []

    # FATURALAR (Borç)
    for fat in Fatura.objects.filter(tedarikci=tedarikci):
        hareketler.append({
            'tarih': fat.tarih,
            'aciklama': f"Fatura #{fat.fatura_no}",
            'borc': fat.genel_toplam,
            'alacak': Decimal('0')
        })

    # HAKEDİŞLER (Borç)
    for hk in Hakedis.objects.filter(satinalma__teklif__tedarikci=tedarikci, onay_durumu=True):
        hareketler.append({
            'tarih': hk.tarih,
            'aciklama': f"Hakediş #{hk.hakedis_no}",
            'borc': hk.odenecek_net_tutar,
            'alacak': Decimal('0')
        })

    # ÖDEMELER (Alacak)
    for o in Odeme.objects.filter(tedarikci=tedarikci):
        hareketler.append({
            'tarih': o.tarih,
            'aciklama': f"Ödeme ({o.odeme_turu})",
            'borc': Decimal('0'),
            'alacak': o.tutar
        })

    # Sıralama ve Bakiye
    hareketler.sort(key=lambda x: x['tarih'])
    bakiye = Decimal('0.00')
    for h in hareketler:
        bakiye += (h['borc'] - h['alacak'])
        h['bakiye'] = bakiye

    return render(request, 'cari_ekstre.html', {
        'tedarikci': tedarikci,
        'hareketler': hareketler
    })


@login_required
def odeme_dashboard(request):
    """
    YENİ MANTIK: Fatura ve Hakediş Özetleri
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    # Hakediş Toplamı
    hakedis_toplam = Hakedis.objects.filter(onay_durumu=True).aggregate(t=Sum('odenecek_net_tutar'))['t'] or Decimal('0.00')

    # Fatura Borcu (Eskiden malzeme_borcu idi)
    toplam_fatura = Fatura.objects.aggregate(t=Sum('genel_toplam'))['t'] or Decimal('0')

    toplam_odenen = Odeme.objects.aggregate(t=Sum('tutar'))['t'] or Decimal('0.00')
    
    # Kalan
    kalan_borc = (hakedis_toplam + toplam_fatura) - toplam_odenen

    context = {
        'hakedis_toplam': hakedis_toplam,
        'malzeme_borcu': toplam_fatura, 
        'toplam_borc': kalan_borc,
        'son_hakedisler': Hakedis.objects.order_by('-tarih')[:5],
        'son_alimlar': SatinAlma.objects.filter(teklif__malzeme__isnull=False).order_by('-created_at')[:5],
    }
    return render(request, 'odeme_dashboard.html', context)


@login_required
def cek_takibi(request):
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')
    bugun = timezone.now().date()
    cekler = Odeme.objects.filter(odeme_turu='cek').order_by('vade_tarihi')
    toplam_risk = cekler.aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0.00')
    context = {
        'gecikmisler': cekler.filter(vade_tarihi__lt=bugun),
        'yaklasanlar': cekler.filter(vade_tarihi__gte=bugun, vade_tarihi__lte=bugun + timezone.timedelta(days=30)),
        'ileri_tarihliler': cekler.filter(vade_tarihi__gt=bugun + timezone.timedelta(days=30)),
        'toplam_risk': toplam_risk,
        'bugun': bugun
    }
    return render(request, 'cek_takibi.html', context)


@login_required
def cek_durum_degistir(request, odeme_id):
    messages.info(request, "Bu özellik yakında aktif olacak.")
    return redirect('cek_takibi')

@login_required
def finans_ozeti(request):
    return redirect('finans_dashboard')


@login_required
def get_tedarikci_bakiye(request, tedarikci_id):
    """
    YENİ MANTIK: Fatura + Hakediş - Ödeme
    """
    try:
        tedarikci = Tedarikci.objects.get(id=tedarikci_id)
        
        # 1. Hakediş
        hakedis_borc = Hakedis.objects.filter(
            satinalma__teklif__tedarikci=tedarikci, onay_durumu=True
        ).aggregate(t=Sum('odenecek_net_tutar'))['t'] or Decimal('0')
        
        # 2. Fatura
        fatura_borc = Fatura.objects.filter(
            tedarikci=tedarikci
        ).aggregate(t=Sum('genel_toplam'))['t'] or Decimal('0')
        
        # 3. Ödeme
        odenen = Odeme.objects.filter(
            tedarikci=tedarikci
        ).aggregate(t=Sum('tutar'))['t'] or Decimal('0')

        kalan = (hakedis_borc + fatura_borc) - odenen

        return JsonResponse({
            'success': True,
            'kalan_bakiye': float(kalan)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def odeme_sil(request, odeme_id):
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    odeme = get_object_or_404(Odeme, id=odeme_id)
    tedarikci_id = odeme.tedarikci.id

    odeme.delete()

    messages.warning(request, "🗑️ Ödeme kaydı silindi, cari bakiye güncellendi.")
    return redirect('cari_ekstre', tedarikci_id=tedarikci_id) # tedarikci_ekstresi yerine cari_ekstre'ye yönlendirdim