from decimal import Decimal, InvalidOperation
from datetime import date
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


# --- YARDIMCI FONKSİYONLAR ---

def clean_currency_input(value_str):
    """
    Frontend'den gelen '1.250,50' (TR) veya '1250.50' (US) formatlarını
    doğru şekilde Python Decimal formatına çevirir.
    100 katı hatasını önlemek için kritiktir.
    """
    if not value_str:
        return Decimal('0.00')
    
    # Zaten sayıysa direkt çevir
    if isinstance(value_str, (int, float, Decimal)):
        return to_decimal(value_str)

    value_str = str(value_str).strip()
    
    # Hem nokta hem virgül varsa (Binlik ayracı ve ondalık)
    if '.' in value_str and ',' in value_str:
        # Sonuncusu ondalıktır.
        last_dot = value_str.rfind('.')
        last_comma = value_str.rfind(',')
        
        if last_comma > last_dot:
            # Format: 1.250,50 (TR) -> Noktaları sil, virgülü nokta yap
            value_str = value_str.replace('.', '').replace(',', '.')
        else:
            # Format: 1,250.50 (US) -> Virgülleri sil
            value_str = value_str.replace(',', '')
    elif ',' in value_str:
        # Sadece virgül var (12,50 veya 12,500) -> TR ondalık kabul et ve noktaya çevir
        value_str = value_str.replace(',', '.')
    
    try:
        return Decimal(value_str)
    except (InvalidOperation, ValueError):
        return Decimal('0.00')

def get_smart_exchange_rate(obj, guncel_kurlar):
    """
    Fatura veya Hakediş için doğru kuru ve para birimini bulur.
    1. Modelde kayıtlı para birimi var mı?
    2. Kur bilgisi var mı? Yoksa güncel kuru kullan.
    Dönüş: (para_birimi, kur_degeri)
    """
    pb = 'TRY'
    kur = Decimal('1.0')

    # 1. Para Birimi Tespiti
    if hasattr(obj, 'satinalma') and obj.satinalma and obj.satinalma.teklif:
        pb = obj.satinalma.teklif.para_birimi
    elif hasattr(obj, 'para_birimi') and obj.para_birimi:
        pb = obj.para_birimi # Eğer faturada direkt tanımlıysa

    if pb in ['TL', 'TRY']:
        return 'TRY', Decimal('1.0')

    # 2. Kur Tespiti (Önce kayıtlara bak)
    if hasattr(obj, 'kur_degeri') and obj.kur_degeri and to_decimal(obj.kur_degeri) > 0.1:
        kur = to_decimal(obj.kur_degeri)
    elif hasattr(obj, 'satinalma') and obj.satinalma and obj.satinalma.teklif:
        if hasattr(obj.satinalma.teklif, 'kur_degeri') and obj.satinalma.teklif.kur_degeri:
            kur = to_decimal(obj.satinalma.teklif.kur_degeri)
    
    # 3. Kayıtlı Kur Yoksa -> Güncel Kur (TCMB)
    if kur <= 1.01:
        kur = guncel_kurlar.get(pb, Decimal('1.0'))
    
    return pb, kur


# --- VIEW FONKSİYONLARI ---

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
    ÖDEME EKRANI (TAMİR EDİLMİŞ VERSİYON)
    - 100 Katı Hatası Giderildi (clean_currency_input)
    - Dövizli Faturaların TL Karşılığı Düzeltildi (get_smart_exchange_rate)
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    tedarikci_id = request.GET.get('tedarikci_id') or request.POST.get('tedarikci')
    fatura_id = request.GET.get('fatura_id') 

    acik_kalemler = []
    secilen_tedarikci = None
    toplam_guncel_borc_tl = Decimal('0.00')
    guncel_kurlar = tcmb_kur_getir()

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
                kalan_orj = toplam - odenen
                
                if kalan_orj > 0.1:
                    # Akıllı Kur Tespiti
                    pb, kur = get_smart_exchange_rate(hk, guncel_kurlar)
                    tl_karsiligi = kalan_orj * kur
                    
                    aciklama = f"Hakediş #{hk.hakedis_no}"
                    try:
                        if hk.satinalma and hk.satinalma.teklif and hk.satinalma.teklif.is_kalemi:
                            aciklama += f" - {hk.satinalma.teklif.is_kalemi.isim}"
                    except: pass

                    if pb != 'TRY':
                        aciklama += f" <br><span class='badge bg-warning text-dark'>Orj: {kalan_orj:,.2f} {pb} (Kur: {kur})</span>"

                    acik_kalemler.append({
                        'id': hk.id, 'tip': 'Hakedis',
                        'evrak_no': f"Hakediş #{hk.hakedis_no}", 
                        'tarih': hk.tarih,
                        'aciklama': aciklama,
                        'tutar_orj': kalan_orj,
                        'para_birimi': pb,
                        'kur': kur,
                        'tutar': tl_karsiligi, 
                    })
                    toplam_guncel_borc_tl += tl_karsiligi

            # --- 2. FATURALAR ---
            faturalar = Fatura.objects.filter(tedarikci=secilen_tedarikci).order_by('tarih')
            for fat in faturalar:
                odenen_db = Odeme.objects.filter(fatura=fat).aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0')
                odenen_field = to_decimal(getattr(fat, 'odenen_tutar', 0))
                mevcut_odenen = max(odenen_db, odenen_field)
                
                kalan_orj = to_decimal(fat.genel_toplam) - to_decimal(mevcut_odenen)
                
                if kalan_orj > 0.1:
                    # Akıllı Kur Tespiti
                    pb, kur = get_smart_exchange_rate(fat, guncel_kurlar)
                    tl_karsiligi = kalan_orj * kur

                    aciklama_text = fat.aciklama or ""
                    if pb != 'TRY':
                        aciklama_text += f" <br><span class='badge bg-warning text-dark'>Orj: {kalan_orj:,.2f} {pb} (Kur: {kur})</span>"

                    acik_kalemler.append({
                        'id': fat.id, 'tip': 'Fatura',
                        'evrak_no': f"Fatura #{fat.fatura_no}",
                        'tarih': fat.tarih,
                        'aciklama': aciklama_text,
                        'tutar_orj': kalan_orj,
                        'para_birimi': pb,
                        'kur': kur,
                        'tutar': tl_karsiligi,
                    })
                    toplam_guncel_borc_tl += tl_karsiligi

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
                
                # --- KRİTİK: Tutar temizleme ve formatlama ---
                raw_tutar = request.POST.get('tutar', '0')
                odeme.tutar = clean_currency_input(raw_tutar)
                odeme.para_birimi = 'TRY' # Her zaman TL
                odeme.save()
                
                dagitilacak_tl = odeme.tutar
                secilenler = request.POST.getlist('secilen_kalem')
                
                if not secilenler and fatura_id:
                     secilenler = [f"Fatura_{fatura_id}"]

                for secim in secilenler:
                    if dagitilacak_tl <= 0: break
                    try:
                        tip, id_str = secim.split('_')
                        obj_id = int(id_str)
                    except ValueError: continue

                    if tip == 'Hakedis':
                        hk = Hakedis.objects.get(id=obj_id)
                        # Kur bul ve TL'yi orjinale çevir
                        _, kur = get_smart_exchange_rate(hk, guncel_kurlar)
                        odenen_orj = dagitilacak_tl / kur if kur > 0 else dagitilacak_tl
                        
                        hk.fiili_odenen_tutar = to_decimal(hk.fiili_odenen_tutar) + odenen_orj
                        hk.save()
                        
                        if not odeme.bagli_hakedis:
                            odeme.bagli_hakedis = hk
                            odeme.save()
                            
                        dagitilacak_tl -= (odenen_orj * kur)

                    elif tip == 'Fatura':
                        fat = Fatura.objects.get(id=obj_id)
                        
                        # Kur bul ve TL'yi orjinale çevir
                        _, kur = get_smart_exchange_rate(fat, guncel_kurlar)
                        odenen_orj = dagitilacak_tl / kur if kur > 0 else dagitilacak_tl
                        
                        if hasattr(fat, 'odenen_tutar'):
                            mevcut = to_decimal(getattr(fat, 'odenen_tutar', 0))
                            fat.odenen_tutar = mevcut + odenen_orj
                            if fat.odenen_tutar >= (to_decimal(fat.genel_toplam) - Decimal('0.5')):
                                if hasattr(fat, 'durum'): fat.durum = 'odendi'
                            fat.save()
                        
                        if not odeme.fatura:
                            odeme.fatura = fat
                            odeme.save()
                            
                        dagitilacak_tl -= (odenen_orj * kur)

                messages.success(request, f"✅ {odeme.tutar} TL tutarında ödeme işlendi.")
                return redirect('finans_dashboard')
            
            except Exception as e:
                messages.error(request, f"Kayıt hatası: {str(e)}")
    else:
        initial_data = {
            'tarih': timezone.now().date(), 
            'tedarikci': secilen_tedarikci,
            'para_birimi': 'TRY',
        }
        if fatura_id:
             hedef = next((item for item in acik_kalemler if str(item['id']) == str(fatura_id) and item['tip'] == 'Fatura'), None)
             if hedef:
                 initial_data['tutar'] = hedef['tutar']
                 initial_data['aciklama'] = f"{hedef['evrak_no']} Ödemesi"

        form = OdemeForm(initial=initial_data)

    borc_ozeti = {'TL': toplam_guncel_borc_tl}

    return render(request, 'odeme_yap.html', {
        'form': form,
        'tedarikciler': Tedarikci.objects.all(),
        'secilen_tedarikci': secilen_tedarikci,
        'acik_kalemler': acik_kalemler,
        'borc_ozeti': borc_ozeti,
        'toplam_borc_tl': toplam_guncel_borc_tl
    })


@login_required
def finans_dashboard(request):
    return redirect('odeme_dashboard')


@login_required
def cari_ekstre(request, tedarikci_id):
    """
    CARİ EKSTRE - DOĞRU KUR MANTIĞI İLE
    """
    tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
    hareketler = []
    guncel_kurlar = tcmb_kur_getir()

    # 1. FATURALAR
    for fat in Fatura.objects.filter(tedarikci=tedarikci):
        pb, kur = get_smart_exchange_rate(fat, guncel_kurlar)
        tl_borc = to_decimal(fat.genel_toplam) * kur
        
        aciklama = f"Fatura #{fat.fatura_no}"
        if pb != 'TRY':
            aciklama += f"<br><span class='badge bg-light text-dark border'>Orj: {fat.genel_toplam:,.2f} {pb} | Kur: {kur}</span>"

        hareketler.append({
            'tarih': fat.tarih,
            'aciklama': aciklama,
            'borc': tl_borc,
            'alacak': Decimal('0'),
            'tip': 'fatura'
        })

    # 2. HAKEDİŞLER
    for hk in Hakedis.objects.filter(satinalma__teklif__tedarikci=tedarikci, onay_durumu=True):
        pb, kur = get_smart_exchange_rate(hk, guncel_kurlar)
        tl_borc = to_decimal(hk.odenecek_net_tutar) * kur

        aciklama = f"Hakediş #{hk.hakedis_no}"
        if pb != 'TRY':
            aciklama += f"<br><span class='badge bg-light text-dark border'>Orj: {hk.odenecek_net_tutar:,.2f} {pb} | Kur: {kur}</span>"

        hareketler.append({
            'tarih': hk.tarih,
            'aciklama': aciklama,
            'borc': tl_borc,
            'alacak': Decimal('0'),
            'tip': 'hakedis'
        })

    # 3. ÖDEMELER
    for o in Odeme.objects.filter(tedarikci=tedarikci):
        tl_alacak = to_decimal(o.tutar)
        aciklama = f"Ödeme ({o.get_odeme_turu_display()})"
        if o.aciklama: aciklama += f" - {o.aciklama}"

        hareketler.append({
            'tarih': o.tarih,
            'aciklama': aciklama,
            'borc': Decimal('0'),
            'alacak': tl_alacak,
            'tip': 'odeme'
        })

    hareketler.sort(key=lambda x: x['tarih'])
    bakiye = Decimal('0.00')
    for h in hareketler:
        bakiye += (h['borc'] - h['alacak'])
        h['bakiye'] = bakiye

    return render(request, 'cari_ekstre.html', {
        'tedarikci': tedarikci,
        'hareketler': hareketler,
        'son_bakiye': bakiye
    })


@login_required
def odeme_dashboard(request):
    """
    FİNANS KOKPİTİ - TAMAMEN DOLU VERSİYON
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    guncel_kurlar = tcmb_kur_getir()
    
    toplam_borc_tl = Decimal('0.00')
    hakedis_toplam_tl = Decimal('0.00')
    malzeme_borcu_tl = Decimal('0.00')

    # A) Tüm Faturalar (Malzeme)
    for fat in Fatura.objects.all():
        odenen = Odeme.objects.filter(fatura=fat).aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0')
        odenen_field = to_decimal(getattr(fat, 'odenen_tutar', 0))
        mevcut_odenen = max(odenen, odenen_field)
        
        kalan_orj = to_decimal(fat.genel_toplam) - to_decimal(mevcut_odenen)
        
        if kalan_orj > 0.1:
            pb, kur = get_smart_exchange_rate(fat, guncel_kurlar)
            
            tl_tutar = kalan_orj * kur
            toplam_borc_tl += tl_tutar
            malzeme_borcu_tl += tl_tutar

    # B) Onaylı Hakedişler
    for hk in Hakedis.objects.filter(onay_durumu=True):
        kalan_orj = to_decimal(hk.odenecek_net_tutar) - to_decimal(hk.fiili_odenen_tutar)
        if kalan_orj > 0.1:
            pb, kur = get_smart_exchange_rate(hk, guncel_kurlar)
            
            tl_tutar = kalan_orj * kur
            toplam_borc_tl += tl_tutar
            hakedis_toplam_tl += tl_tutar

    son_hakedisler = Hakedis.objects.order_by('-tarih')[:5]
    son_alimlar = SatinAlma.objects.filter(teklif__malzeme__isnull=False).order_by('-created_at')[:5]

    context = {
        'toplam_borc': toplam_borc_tl,
        'hakedis_toplam': hakedis_toplam_tl,
        'malzeme_borcu': malzeme_borcu_tl, 
        'son_hakedisler': son_hakedisler,
        'son_alimlar': son_alimlar,
        'kurlar': guncel_kurlar
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
    return JsonResponse({'success': True, 'kalan_bakiye': 0})

@login_required
def odeme_sil(request, odeme_id):
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')
    odeme = get_object_or_404(Odeme, id=odeme_id)
    if odeme.fatura and hasattr(odeme.fatura, 'odenen_tutar'):
         yeni = to_decimal(odeme.fatura.odenen_tutar) - to_decimal(odeme.tutar)
         odeme.fatura.odenen_tutar = max(yeni, Decimal('0'))
         odeme.fatura.save()
    odeme.delete()
    messages.warning(request, "🗑️ Ödeme kaydı silindi.")
    return redirect('finans_dashboard')