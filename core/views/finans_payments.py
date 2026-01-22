from decimal import Decimal
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


# --- YARDIMCI FONKSİYON: GÜNCEL KURLA TL HESAPLA ---
def get_guncel_tl_karsiligi(tutar_orj, para_birimi, guncel_kurlar):
    """
    Verilen orijinal tutarı, güncel kurlar sözlüğünü kullanarak TL'ye çevirir.
    Eğer para birimi TL ise 1 ile çarpar.
    """
    tutar = to_decimal(tutar_orj)
    
    if para_birimi == 'TRY' or para_birimi == 'TL':
        return tutar, Decimal('1.0')
    
    # Kur sözlüğünden kuru al (yoksa 1 kabul et)
    kur = guncel_kurlar.get(para_birimi, Decimal('1.0'))
    tl_karsiligi = tutar * kur
    return tl_karsiligi, kur


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
    ÖDEME EKRANI - HER ŞEY TL BAZLI GÖSTERİLİR VE İŞLENİR.
    Kullanıcı borçları TL karşılığı ile görür, ödemeyi TL olarak yapar.
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    tedarikci_id = request.GET.get('tedarikci_id') or request.POST.get('tedarikci')
    fatura_id = request.GET.get('fatura_id') 

    acik_kalemler = []
    secilen_tedarikci = None
    
    # Sayfanın en üstünde gösterilecek toplam borç (Güncel Kurla TL)
    toplam_guncel_borc_tl = Decimal('0.00')
    
    # Güncel kurları bir kere çekelim (Performans için)
    guncel_kurlar = tcmb_kur_getir()

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
                kalan_orj = toplam - odenen
                
                if kalan_orj > 0.1:
                    # Para birimini bul
                    para_birimi = 'TRY'
                    aciklama = f"Hakediş #{hk.hakedis_no}"
                    try:
                        if hk.satinalma and hk.satinalma.teklif:
                            para_birimi = hk.satinalma.teklif.para_birimi
                            if hk.satinalma.teklif.is_kalemi:
                                aciklama += f" - {hk.satinalma.teklif.is_kalemi.isim}"
                    except ObjectDoesNotExist:
                        pass

                    # Güncel TL karşılığını hesapla
                    tl_karsiligi, kur = get_guncel_tl_karsiligi(kalan_orj, para_birimi, guncel_kurlar)
                    
                    # Bilgi notuna ekle (Dövizli ise)
                    if para_birimi != 'TRY':
                        aciklama += f" <br><span class='badge bg-warning text-dark'>Orj: {kalan_orj:,.2f} {para_birimi} (Kur: {kur})</span>"

                    acik_kalemler.append({
                        'id': hk.id, 'tip': 'Hakedis',
                        'evrak_no': f"Hakediş #{hk.hakedis_no}", 
                        'tarih': hk.tarih,
                        'aciklama': aciklama,
                        'tutar_orj': kalan_orj,
                        'para_birimi': para_birimi,
                        'kur': kur,
                        'tutar': tl_karsiligi, # Listede görünecek TL tutarı
                    })
                    toplam_guncel_borc_tl += tl_karsiligi

            # --- 2. FATURALAR ---
            faturalar = Fatura.objects.filter(tedarikci=secilen_tedarikci).order_by('tarih')
            for fat in faturalar:
                # Ödenen tutarı bul (En güvenli yöntem: Odeme tablosu + Model Alanı kontrolü)
                odenen_db = Odeme.objects.filter(fatura=fat).aggregate(toplam=Sum('tutar'))['toplam'] or Decimal('0')
                odenen_field = to_decimal(getattr(fat, 'odenen_tutar', 0))
                
                # Faturanın 'odenen_tutar' alanı daha güncel olabilir
                mevcut_odenen = max(odenen_db, odenen_field)
                
                kalan_orj = to_decimal(fat.genel_toplam) - to_decimal(mevcut_odenen)
                
                if kalan_orj > 0.1:
                    para_birimi = 'TRY'
                    aciklama_text = fat.aciklama or ""
                    try:
                        if fat.satinalma and fat.satinalma.teklif:
                            para_birimi = fat.satinalma.teklif.para_birimi
                    except ObjectDoesNotExist:
                        pass

                    tl_karsiligi, kur = get_guncel_tl_karsiligi(kalan_orj, para_birimi, guncel_kurlar)

                    if para_birimi != 'TRY':
                        aciklama_text += f" <br><span class='badge bg-warning text-dark'>Orj: {kalan_orj:,.2f} {para_birimi} (Kur: {kur})</span>"

                    acik_kalemler.append({
                        'id': fat.id, 'tip': 'Fatura',
                        'evrak_no': f"Fatura #{fat.fatura_no}",
                        'tarih': fat.tarih,
                        'aciklama': aciklama_text,
                        'tutar_orj': kalan_orj,
                        'para_birimi': para_birimi,
                        'kur': kur,
                        'tutar': tl_karsiligi, # Ekranda TL görünecek
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
                
                # Ödeme her zaman TL olarak kaydedilecek (Kullanıcı TL görüyor)
                odeme.para_birimi = 'TRY'
                odeme.save()
                
                # Kullanıcının girdiği TL tutar
                dagitilacak_tl = to_decimal(odeme.tutar)
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
                        
                        # Hakedişin döviz cinsini bul
                        hk_pb = 'TRY'
                        if hk.satinalma and hk.satinalma.teklif:
                            hk_pb = hk.satinalma.teklif.para_birimi
                        
                        # TL ödemeyi Hakedişin para birimine çevirip düşeceğiz (Güncel Kurla)
                        _, kur = get_guncel_tl_karsiligi(1, hk_pb, guncel_kurlar)
                        
                        # TL -> ORJİNAL
                        odenen_orj = dagitilacak_tl / kur if kur > 0 else dagitilacak_tl
                        
                        # Hakedişten düş
                        hk.fiili_odenen_tutar = to_decimal(hk.fiili_odenen_tutar) + odenen_orj
                        hk.save()
                        
                        if not odeme.bagli_hakedis:
                            odeme.bagli_hakedis = hk
                            odeme.save()
                            
                        # Dağıtılan miktarı (TL) düş
                        dagitilacak_tl -= (odenen_orj * kur)

                    elif tip == 'Fatura':
                        fat = Fatura.objects.get(id=obj_id)
                        
                        fat_pb = 'TRY'
                        if fat.satinalma and fat.satinalma.teklif:
                            fat_pb = fat.satinalma.teklif.para_birimi
                        
                        _, kur = get_guncel_tl_karsiligi(1, fat_pb, guncel_kurlar)
                        odenen_orj = dagitilacak_tl / kur if kur > 0 else dagitilacak_tl
                        
                        # Faturadan düş
                        if hasattr(fat, 'odenen_tutar'):
                            mevcut = to_decimal(getattr(fat, 'odenen_tutar', 0))
                            fat.odenen_tutar = mevcut + odenen_orj
                            
                            # Kuruş farklarını tolere et
                            if fat.odenen_tutar >= (to_decimal(fat.genel_toplam) - Decimal('0.5')):
                                if hasattr(fat, 'durum'): fat.durum = 'odendi'
                            fat.save()
                        
                        if not odeme.fatura:
                            odeme.fatura = fat
                            odeme.save()
                            
                        dagitilacak_tl -= (odenen_orj * kur)

                messages.success(request, f"✅ {odeme.tutar} TL tutarında ödeme alındı. (Güncel kurlarla ilgili döviz bakiyelerinden düşüldü)")
                return redirect('finans_dashboard')
            
            except Exception as e:
                messages.error(request, f"Kayıt hatası: {str(e)}")
    else:
        # GET
        initial_data = {
            'tarih': timezone.now().date(), 
            'tedarikci': secilen_tedarikci,
            'para_birimi': 'TRY', # Her zaman TL
        }
        if fatura_id:
             hedef = next((item for item in acik_kalemler if str(item['id']) == str(fatura_id) and item['tip'] == 'Fatura'), None)
             if hedef:
                 initial_data['tutar'] = hedef['tutar'] # TL Karşılığı
                 initial_data['aciklama'] = f"{hedef['evrak_no']} Ödemesi"

        form = OdemeForm(initial=initial_data)

    # Şablona 'borc_ozeti' yerine 'toplam_borc_tl' gönderiyoruz çünkü her şey TL oldu
    # Eski şablon yapısı dict bekliyorsa diye 'borc_ozeti' de bırakıyoruz (İçinde tek TL var)
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
    CARİ EKSTRE - TAMAMEN TL BAZLI GÖSTERİM (TARİHİ KURLARLA)
    """
    tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
    hareketler = []

    # 1. FATURALAR
    for fat in Fatura.objects.filter(tedarikci=tedarikci):
        kur = Decimal('1.0')
        pb = 'TRY'
        try:
            if fat.satinalma and fat.satinalma.teklif:
                pb = fat.satinalma.teklif.para_birimi
                kur = to_decimal(fat.satinalma.teklif.kur_degeri)
        except: pass
        
        # TL Tutar Hesapla
        tl_borc = to_decimal(fat.genel_toplam) * kur
        
        aciklama = f"Fatura #{fat.fatura_no}"
        if pb != 'TRY':
            aciklama += f" <br><small class='text-muted'>(Orj: {fat.genel_toplam:,.2f} {pb} | Kur: {kur})</small>"

        hareketler.append({
            'tarih': fat.tarih,
            'aciklama': aciklama,
            'borc': tl_borc,
            'alacak': Decimal('0'),
            'tip': 'fatura'
        })

    # 2. HAKEDİŞLER
    for hk in Hakedis.objects.filter(satinalma__teklif__tedarikci=tedarikci, onay_durumu=True):
        kur = Decimal('1.0')
        pb = 'TRY'
        try:
            if hk.satinalma and hk.satinalma.teklif:
                pb = hk.satinalma.teklif.para_birimi
                kur = to_decimal(hk.satinalma.teklif.kur_degeri)
        except: pass

        tl_borc = to_decimal(hk.odenecek_net_tutar) * kur

        aciklama = f"Hakediş #{hk.hakedis_no}"
        if pb != 'TRY':
            aciklama += f" <br><small class='text-muted'>(Orj: {hk.odenecek_net_tutar:,.2f} {pb} | Kur: {kur})</small>"

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
        # Ödeme her zaman TL kabul ediliyor

        hareketler.append({
            'tarih': o.tarih,
            'aciklama': f"Ödeme ({o.odeme_turu})",
            'borc': Decimal('0'),
            'alacak': tl_alacak,
            'tip': 'odeme'
        })

    # Sıralama ve Yürüyen Bakiye
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
    FİNANS KOKPİTİ - TEK PARA BİRİMİ (TL)
    Tüm borçlar GÜNCEL KUR ile TL'ye çevrilerek toplanır.
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
            pb = 'TRY'
            try:
                if fat.satinalma and fat.satinalma.teklif:
                    pb = fat.satinalma.teklif.para_birimi
            except ObjectDoesNotExist: pass
            
            tl_tutar, _ = get_guncel_tl_karsiligi(kalan_orj, pb, guncel_kurlar)
            toplam_borc_tl += tl_tutar
            malzeme_borcu_tl += tl_tutar

    # B) Onaylı Hakedişler
    for hk in Hakedis.objects.filter(onay_durumu=True):
        kalan_orj = to_decimal(hk.odenecek_net_tutar) - to_decimal(hk.fiili_odenen_tutar)
        if kalan_orj > 0.1:
            pb = 'TRY'
            try:
                if hk.satinalma and hk.satinalma.teklif:
                    pb = hk.satinalma.teklif.para_birimi
            except ObjectDoesNotExist: pass
            
            tl_tutar, _ = get_guncel_tl_karsiligi(kalan_orj, pb, guncel_kurlar)
            toplam_borc_tl += tl_tutar
            hakedis_toplam_tl += tl_tutar

    # Diğer Veriler
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
    # Bu AJAX çağrısı artık karmaşıklaştı, şimdilik 0 dönelim
    return JsonResponse({'success': True, 'kalan_bakiye': 0})

@login_required
def odeme_sil(request, odeme_id):
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')
    odeme = get_object_or_404(Odeme, id=odeme_id)
    if odeme.fatura and hasattr(odeme.fatura, 'odenen_tutar'):
         # Basit iade
         yeni = to_decimal(odeme.fatura.odenen_tutar) - to_decimal(odeme.tutar)
         odeme.fatura.odenen_tutar = max(yeni, Decimal('0'))
         odeme.fatura.save()
    odeme.delete()
    messages.warning(request, "🗑️ Ödeme kaydı silindi.")
    return redirect('finans_dashboard')