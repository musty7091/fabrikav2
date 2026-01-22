from decimal import Decimal
from datetime import date  # <--- EKSİK OLAN BU SATIR EKLENDİ
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse

# Modeller ve Formlar
from core.models import (
    SatinAlma, Hakedis, Odeme, Tedarikci, Fatura, GiderKategorisi
)
from core.forms import HakedisForm, OdemeForm
from core.views.guvenlik import yetki_kontrol
from core.utils import to_decimal, tcmb_kur_getir
from core.services.finans_payments import PaymentService


@login_required
def hakedis_ekle(request, siparis_id):
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
    GELİŞMİŞ ÖDEME MODÜLÜ (NİHAİ VERSİYON)
    1. Hakediş ve Fatura borçlarını çeker.
    2. Borçları para birimine göre (TL, USD, EUR) gruplar.
    3. Seçilen tutarı açık kalemlere dağıtır.
    4. 'RelatedObjectDoesNotExist' ve küsurat hatalarına karşı korumalıdır.
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    tedarikci_id = request.GET.get('tedarikci_id') or request.POST.get('tedarikci')
    fatura_id = request.GET.get('fatura_id') 

    acik_kalemler = []
    secilen_tedarikci = None
    borc_ozeti = {} 
    varsayilan_para_birimi = 'TL'

    # Fatura ID ile gelindiyse tedarikçiyi bul
    if fatura_id and not tedarikci_id:
        fatura_obj = get_object_or_404(Fatura, id=fatura_id)
        tedarikci_id = fatura_obj.tedarikci.id

    if tedarikci_id:
        try:
            secilen_tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)

            # --- 1. HAKEDİŞLER ---
            hakedisler = Hakedis.objects.filter(
                satinalma__teklif__tedarikci=secilen_tedarikci,
                onay_durumu=True
            )
            for hk in hakedisler:
                toplam = to_decimal(hk.odenecek_net_tutar)
                odenen = to_decimal(hk.fiili_odenen_tutar)
                kalan = toplam - odenen
                
                if kalan > 0.1:
                    curr = 'TL'
                    aciklama = f"Hakediş #{hk.hakedis_no}"
                    try:
                        if hk.satinalma and hk.satinalma.teklif:
                            curr = hk.satinalma.teklif.para_birimi
                            if hk.satinalma.teklif.is_kalemi:
                                aciklama += f" - {hk.satinalma.teklif.is_kalemi.isim}"
                    except ObjectDoesNotExist:
                        pass

                    acik_kalemler.append({
                        'id': hk.id, 'tip': 'Hakedis',
                        'evrak_no': f"Hakediş #{hk.hakedis_no}", 
                        'tarih': hk.tarih,
                        'aciklama': aciklama,
                        'tutar': toplam,
                        'kalan': kalan,
                        'para_birimi': curr
                    })

            # --- 2. FATURALAR ---
            faturalar = Fatura.objects.filter(tedarikci=secilen_tedarikci).order_by('tarih')
            for fat in faturalar:
                # Ödenen tutarı en güvenli şekilde bul (DB vs Model Field)
                odenen_db = Odeme.objects.filter(fatura=fat).aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0')
                odenen_field = to_decimal(getattr(fat, 'odenen_tutar', 0))
                
                mevcut_odenen = max(odenen_db, odenen_field)
                genel_toplam = to_decimal(fat.genel_toplam)
                kalan = genel_toplam - to_decimal(mevcut_odenen)
                
                if kalan > 0.1:
                    curr = 'TL'
                    try:
                        if fat.satinalma and fat.satinalma.teklif:
                            curr = fat.satinalma.teklif.para_birimi
                    except ObjectDoesNotExist:
                        pass

                    if str(fat.id) == str(fatura_id):
                        varsayilan_para_birimi = curr

                    acik_kalemler.append({
                        'id': fat.id, 'tip': 'Fatura',
                        'evrak_no': f"Fatura #{fat.fatura_no}",
                        'tarih': fat.tarih,
                        'aciklama': fat.aciklama or '',
                        'tutar': genel_toplam,
                        'kalan': kalan,
                        'para_birimi': curr
                    })

            # --- BORÇ ÖZETİ (Sol Panel İçin) ---
            for kalem in acik_kalemler:
                pb = kalem['para_birimi']
                if pb not in borc_ozeti:
                    borc_ozeti[pb] = Decimal('0')
                borc_ozeti[pb] += kalem['kalan']
            
            # Varsayılan para birimi ayarı
            if acik_kalemler and varsayilan_para_birimi == 'TL' and acik_kalemler[0]['para_birimi'] != 'TL':
                varsayilan_para_birimi = acik_kalemler[0]['para_birimi']

        except Exception as e:
            messages.error(request, f"Veri hatası: {str(e)}")

    # --- POST İŞLEMİ (KAYDET) ---
    if request.method == 'POST':
        form = OdemeForm(request.POST)
        if form.is_valid():
            try:
                odeme = form.save(commit=False)
                if secilen_tedarikci:
                    odeme.tedarikci = secilen_tedarikci
                odeme.save()
                
                secilenler = request.POST.getlist('secilen_kalem')
                dagitilacak = to_decimal(odeme.tutar)
                
                if not secilenler and fatura_id:
                     secilenler = [f"Fatura_{fatura_id}"]

                for secim in secilenler:
                    if dagitilacak <= 0: break
                    try:
                        tip, id_str = secim.split('_')
                        obj_id = int(id_str)
                    except ValueError:
                        continue

                    if tip == 'Hakedis':
                        hk = Hakedis.objects.get(id=obj_id)
                        borc = to_decimal(hk.odenecek_net_tutar) - to_decimal(hk.fiili_odenen_tutar)
                        odenecek = min(dagitilacak, borc)
                        hk.fiili_odenen_tutar = to_decimal(hk.fiili_odenen_tutar) + odenecek
                        hk.save()
                        
                        # Ödemeyi hakedişe bağla
                        if not odeme.bagli_hakedis:
                            odeme.bagli_hakedis = hk
                            odeme.save()
                            
                        dagitilacak -= odenecek

                    elif tip == 'Fatura':
                        fat = Fatura.objects.get(id=obj_id)
                        # Güncel bakiye
                        odenen_db = Odeme.objects.filter(fatura=fat).aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0')
                        mevcut_odeme = odenen_db
                        if hasattr(fat, 'odenen_tutar') and fat.odenen_tutar > odenen_db:
                            mevcut_odeme = fat.odenen_tutar
                            
                        borc = to_decimal(fat.genel_toplam) - to_decimal(mevcut_odeme)
                        odenecek = min(dagitilacak, borc)
                        
                        if hasattr(fat, 'odenen_tutar'):
                            fat.odenen_tutar = to_decimal(mevcut_odeme) + odenecek
                            if fat.odenen_tutar >= fat.genel_toplam:
                                if hasattr(fat, 'durum'): fat.durum = 'odendi'
                            fat.save()
                        
                        # Ödemeyi faturaya bağla
                        if not odeme.fatura:
                            odeme.fatura = fat
                            odeme.save()
                            
                        dagitilacak -= odenecek

                messages.success(request, f"✅ {odeme.tutar} {odeme.para_birimi} ödeme başarıyla işlendi.")
                return redirect('finans_dashboard')
            
            except Exception as e:
                messages.error(request, f"Kayıt hatası: {str(e)}")
    else:
        # GET
        initial_data = {
            'tarih': timezone.now().date(), 
            'tedarikci': secilen_tedarikci,
            'para_birimi': varsayilan_para_birimi,
        }
        if fatura_id:
             hedef = next((item for item in acik_kalemler if str(item['id']) == str(fatura_id) and item['tip'] == 'Fatura'), None)
             if hedef:
                 initial_data['tutar'] = hedef['kalan']
                 initial_data['aciklama'] = f"{hedef['evrak_no']} Ödemesi"

        form = OdemeForm(initial=initial_data)

    return render(request, 'odeme_yap.html', {
        'form': form,
        'tedarikciler': Tedarikci.objects.all(),
        'secilen_tedarikci': secilen_tedarikci,
        'acik_kalemler': acik_kalemler,
        'borc_ozeti': borc_ozeti
    })


@login_required
def finans_dashboard(request):
    """
    FİNANS KOKPİTİ (NİHAİ VERSİYON - PARA BİRİMİ AYRIMLI)
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    # --- 1. Borçları Para Birimine Göre Hesapla ---
    borc_listesi = {} # {'TL': 1000, 'USD': 500}

    # A) Tüm Faturalar (Performans için ödenmemişleri almak daha iyi olur ama güvenlik için tümünü tarıyoruz)
    all_faturalar = Fatura.objects.all()
    
    for fat in all_faturalar:
        # Para birimi tespiti
        curr = 'TL'
        try:
            if fat.satinalma and fat.satinalma.teklif:
                curr = fat.satinalma.teklif.para_birimi
        except ObjectDoesNotExist:
            pass

        # Kalan tutarı hesapla
        odenen = Odeme.objects.filter(fatura=fat).aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0')
        kalan = to_decimal(fat.genel_toplam) - to_decimal(odenen)
        
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
    # Bekleyen faturalar için basit bir sorgu (Vade tarihi yakın olanlar)
    bekleyen_faturalar = Fatura.objects.all().order_by('tarih')[:6]

    # Giderler
    gider_labels, gider_data = [], []
    harcama_tutari = Decimal('0.00')
    for gk in GiderKategorisi.objects.all():
        tutar = sum(to_decimal(h.tl_tutar) for h in gk.harcamalar.all())
        if tutar > 0:
            gider_labels.append(gk.isim)
            gider_data.append(float(tutar))
            harcama_tutari += tutar

    context = {
        'borc_listesi': borc_listesi, 
        'toplam_odeme_bu_ay': toplam_odeme_bu_ay,
        'son_odemeler': son_odemeler,
        'bekleyen_faturalar': bekleyen_faturalar,
        'gider_labels': gider_labels,
        'gider_data': gider_data,
        'harcama_tutari': harcama_tutari,
        'kurlar': tcmb_kur_getir(),
    }
    return render(request, 'finans_dashboard.html', context)


@login_required
def cari_ekstre(request, tedarikci_id):
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
    Ödeme Kokpiti: Borçları para birimine göre ayrıştırır.
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    # --- 1. Borçları Para Birimine Göre Hesapla ---
    borc_listesi = {} # {'TL': 1000, 'USD': 500}

    # A) Tüm Faturalar
    all_faturalar = Fatura.objects.all()
    
    for fat in all_faturalar:
        curr = 'TL'
        try:
            if fat.satinalma and fat.satinalma.teklif:
                curr = fat.satinalma.teklif.para_birimi
        except ObjectDoesNotExist:
            pass

        odenen = Odeme.objects.filter(fatura=fat).aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0')
        kalan = to_decimal(fat.genel_toplam) - to_decimal(odenen)
        
        if kalan > 0.1:
            if curr not in borc_listesi: borc_listesi[curr] = Decimal('0')
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
            if curr not in borc_listesi: borc_listesi[curr] = Decimal('0')
            borc_listesi[curr] += kalan

    # --- 2. Diğer Veriler ---
    son_hakedisler = Hakedis.objects.order_by('-tarih')[:5]
    son_alimlar = SatinAlma.objects.filter(teklif__malzeme__isnull=False).order_by('-created_at')[:5]

    context = {
        'borc_listesi': borc_listesi, 
        'son_hakedisler': son_hakedisler,
        'son_alimlar': son_alimlar,
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
    
    # Silinen ödemeyi faturadan düş
    if odeme.fatura and hasattr(odeme.fatura, 'odenen_tutar'):
         yeni_tutar = to_decimal(odeme.fatura.odenen_tutar) - to_decimal(odeme.tutar)
         odeme.fatura.odenen_tutar = max(yeni_tutar, Decimal('0'))
         # Fatura durumu güncelleme
         if odeme.fatura.odenen_tutar < odeme.fatura.genel_toplam:
             # Modelde durum varsa güncelle
             if hasattr(odeme.fatura, 'durum'):
                 odeme.fatura.durum = 'bekliyor' # veya kismen_odendi
         odeme.fatura.save()

    odeme.delete()
    messages.warning(request, "🗑️ Ödeme kaydı silindi.")
    return redirect('finans_dashboard')