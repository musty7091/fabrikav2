from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from decimal import Decimal
from core.models import Tedarikci, Fatura, Hakedis, Odeme, Malzeme, DepoHareket
from core.utils import to_decimal

@login_required
def cari_ekstresi(request):
    """
    Tedarikçi Cari Ekstresi
    """
    tedarikciler = Tedarikci.objects.all().order_by('firma_unvani')
    secilen_tedarikci = None
    hareketler = []
    
    tedarikci_id = request.GET.get('tedarikci')
    tarih1 = request.GET.get('d1')
    tarih2 = request.GET.get('d2')

    toplam_borc = Decimal('0')
    toplam_alacak = Decimal('0')
    genel_bakiye = Decimal('0')

    if tedarikci_id:
        secilen_tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
        
        # 1. Verileri Çek
        faturalar = Fatura.objects.filter(tedarikci=secilen_tedarikci)
        hakedisler = Hakedis.objects.filter(satinalma__teklif__tedarikci=secilen_tedarikci, onay_durumu=True)
        odemeler = Odeme.objects.filter(tedarikci=secilen_tedarikci)

        # Tarih Filtresi
        if tarih1:
            faturalar = faturalar.filter(tarih__gte=tarih1)
            hakedisler = hakedisler.filter(tarih__gte=tarih1)
            odemeler = odemeler.filter(tarih__gte=tarih1)
        if tarih2:
            faturalar = faturalar.filter(tarih__lte=tarih2)
            hakedisler = hakedisler.filter(tarih__lte=tarih2)
            odemeler = odemeler.filter(tarih__lte=tarih2)

        # 2. Listeyi Oluştur
        # Faturalar
        for fat in faturalar:
            tutar = getattr(fat, 'genel_toplam', Decimal('0'))
            hareketler.append({
                'tarih': fat.tarih,
                'evrak': fat.fatura_no,
                'aciklama': f"Fatura: {fat.aciklama or ''}",
                'borc': tutar,
                'alacak': Decimal('0'),
                'tip': 'Fatura'
            })

        # Hakedişler
        for hk in hakedisler:
            hareketler.append({
                'tarih': hk.tarih,
                'evrak': f"HK-{hk.hakedis_no}",
                'aciklama': f"Hakediş ({hk.satinalma.teklif.is_kalemi.isim if hk.satinalma.teklif.is_kalemi else 'İşçilik'})",
                'borc': hk.odenecek_net_tutar,
                'alacak': Decimal('0'),
                'tip': 'Hakediş'
            })

        # Ödemeler
        for odeme in odemeler:
            hareketler.append({
                'tarih': odeme.tarih,
                'evrak': "-",
                'aciklama': f"Ödeme: {odeme.get_odeme_turu_display()}",
                'borc': Decimal('0'),
                'alacak': odeme.tutar,
                'tip': 'Ödeme'
            })

        # 3. Sırala ve Bakiye Hesapla
        hareketler.sort(key=lambda x: x['tarih'])

        bakiye = Decimal('0')
        for h in hareketler:
            h['borc'] = to_decimal(h['borc'])
            h['alacak'] = to_decimal(h['alacak'])
            
            bakiye += (h['borc'] - h['alacak'])
            h['bakiye'] = bakiye
            
            toplam_borc += h['borc']
            toplam_alacak += h['alacak']
        
        genel_bakiye = toplam_borc - toplam_alacak

    context = {
        'tedarikciler': tedarikciler,
        'secilen_tedarikci': secilen_tedarikci,
        'hareketler': hareketler,
        'toplam_borc': toplam_borc,
        'toplam_alacak': toplam_alacak,
        'genel_bakiye': genel_bakiye,
        'filtre_d1': tarih1,
        'filtre_d2': tarih2,
    }

    return render(request, 'cari_ekstre.html', context)


@login_required
def stok_ekstresi(request):
    """
    Malzeme Stok Ekstresi
    Düzeltme: Modeldeki 'depo_tipi' alanına göre kontrol yapıldı.
    """
    malzemeler = Malzeme.objects.all()
    secilen_malzeme = None
    hareketler = []
    
    malzeme_id = request.GET.get('malzeme')
    if malzeme_id:
        secilen_malzeme = get_object_or_404(Malzeme, id=malzeme_id)
        
        # Hareketleri tarih ve ID sırasına göre çek
        depo_hareketleri = DepoHareket.objects.filter(malzeme=secilen_malzeme).order_by('tarih', 'id')
        
        stok_bakiye = Decimal('0')
        
        for dh in depo_hareketleri:
            miktar = to_decimal(dh.miktar)
            giris = Decimal('0')
            cikis = Decimal('0')
            
            # --- STOK HAREKET MANTIĞI ---
            
            if dh.islem_turu == 'giris':
                giris = miktar
                
                # KRİTİK KONTROL:
                # Sizin modelinizde "Kullanım / Sarf Yeri" -> "CONSUMPTION" olarak tutuluyor.
                # Eğer ürün bu tip bir depoya girdiyse, stok bakiyesini artırmıyoruz (Tüketildi).
                
                if dh.depo and dh.depo.depo_tipi == 'CONSUMPTION':
                    pass # Bakiyeye dokunma, bu bir tüketim girişidir.
                else:
                    stok_bakiye += miktar

            elif dh.islem_turu in ['cikis', 'transfer', 'iade']:
                cikis = miktar
                stok_bakiye -= miktar
            
            # İşlem adını belirle
            islem_adi = dh.get_islem_turu_display() if hasattr(dh, 'get_islem_turu_display') else dh.islem_turu

            hareketler.append({
                'tarih': dh.tarih,
                'islem': islem_adi,
                'aciklama': dh.aciklama,
                'giris': giris,
                'cikis': cikis,
                'bakiye': stok_bakiye,
                'depo': dh.depo.isim if dh.depo else "-",
                # Template'de kullanmak isterseniz diye tipi de ekledim
                'depo_tipi': dh.depo.get_depo_tipi_display() if dh.depo else ""
            })

    return render(request, 'stok_ekstresi.html', {
        'malzemeler': malzemeler,
        'secilen_malzeme': secilen_malzeme,
        'hareketler': hareketler
    })