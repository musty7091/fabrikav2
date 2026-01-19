import json
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Q, F, Value, DecimalField
from django.db.models.functions import Coalesce
from django.http import JsonResponse, HttpResponse
from core.models import Malzeme, DepoHareket, MalzemeTalep, SatinAlma, Depo, DepoTransfer
from core.forms import DepoTransferForm
from core.services import StockService
from .guvenlik import yetki_kontrol

@login_required
def depo_dashboard(request):
    if not yetki_kontrol(request.user, ['SAHA_EKIBI', 'OFIS_VE_SATINALMA', 'YONETICI']): 
        return redirect('erisim_engellendi')
    
    # Uzman Formülü: Giriş - Çıkış - İade (Dashboard için Coalesce ile koruma sağlandı)
    malzemeler = Malzeme.objects.annotate(
        giren=Coalesce(Sum('hareketler__miktar', filter=Q(hareketler__islem_turu='giris')), Value(0, output_field=DecimalField())),
        cikan=Coalesce(Sum('hareketler__miktar', filter=Q(hareketler__islem_turu='cikis')), Value(0, output_field=DecimalField())),
        iadeler=Coalesce(Sum('hareketler__miktar', filter=Q(hareketler__islem_turu='iade')), Value(0, output_field=DecimalField())),
    ).annotate(hesaplanan_stok=F('giren') - F('cikan') - F('iadeler'))

    depo_ozeti = []
    for mal in malzemeler:
        stok_degeri = mal.hesaplanan_stok
        durum_renk = "danger" if stok_degeri <= mal.kritik_stok else ("warning" if stok_degeri <= (mal.kritik_stok * 1.5) else "success")
        depo_ozeti.append({
            'isim': mal.isim, 
            'birim': mal.get_birim_display(), 
            'stok': stok_degeri, 
            'durum_renk': durum_renk
        })

    context = {
        'depo_ozeti': depo_ozeti,
        'son_iadeler': DepoHareket.objects.filter(islem_turu='iade').order_by('-tarih')[:5],
        'bekleyen_talepler': MalzemeTalep.objects.filter(durum='bekliyor').order_by('-oncelik')[:10],
        'bekleyen_talep_sayisi': MalzemeTalep.objects.filter(durum='bekliyor').count()
    }
    return render(request, 'depo_dashboard.html', context)

@login_required
def stok_listesi(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']): 
        return redirect('erisim_engellendi')
    
    search = request.GET.get('search', '')
    
    # KRİTİK DÜZELTME: 
    # hesaplanan_stok formülünde girişleri toplarken kullanım depolarını (is_kullanim_yeri=True) hariç tutuyoruz.
    malzemeler = Malzeme.objects.annotate(
        hesaplanan_stok=Coalesce(
            Sum('hareketler__miktar', filter=Q(hareketler__islem_turu='giris', hareketler__depo__is_kullanim_yeri=False)), 
            Value(0, output_field=DecimalField())
        ) - Coalesce(
            Sum('hareketler__miktar', filter=Q(hareketler__islem_turu='cikis')), 
            Value(0, output_field=DecimalField())
        ) - Coalesce(
            Sum('hareketler__miktar', filter=Q(hareketler__islem_turu='iade')), 
            Value(0, output_field=DecimalField())
        )
    )
    
    if search:
        malzemeler = malzemeler.filter(isim__icontains=search)
    
    # Görsel Durum Belirleme (Renkler ve Etiketler)
    for m in malzemeler:
        stok = m.hesaplanan_stok
        limit = Decimal(str(m.kritik_stok or 0))
        
        if stok <= 0:
            m.stok_durumu = "YOK"
            m.stok_renk = "secondary"
        elif stok <= limit:
            m.stok_durumu = "KRİTİK"
            m.stok_renk = "danger"
        elif stok <= (limit * Decimal('1.5')):
            m.stok_durumu = "AZALDI"
            m.stok_renk = "warning"
        else:
            m.stok_durumu = "YETERLİ"
            m.stok_renk = "success"

    # İstatistikler (Filtrelenmiş stok üzerinden)
    kritik_sayisi = sum(1 for m in malzemeler if 0 < m.hesaplanan_stok <= Decimal(str(m.kritik_stok or 0)))
    yok_sayisi = sum(1 for m in malzemeler if m.hesaplanan_stok <= 0)

    return render(request, 'stok_listesi.html', {
        'malzemeler': malzemeler, 
        'search_query': search, 
        'kritik_sayisi': kritik_sayisi,
        'yok_sayisi': yok_sayisi
    })

@login_required
def depo_transfer(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'DEPO_SORUMLUSU', 'SAHA_VE_DEPO', 'YONETICI']): 
        return redirect('erisim_engellendi')
    
    siparis_id = request.GET.get('siparis_id') or request.POST.get('siparis_id')
    siparis, initial_data = None, {'tarih': timezone.now().date()}

    if siparis_id:
        siparis = get_object_or_404(SatinAlma, id=siparis_id)
        # Çıkış özeti
        cikis_ozeti = DepoHareket.objects.filter(siparis=siparis, islem_turu='cikis').aggregate(toplam=Sum('miktar'))
        cikis_toplami = cikis_ozeti['toplam'] or 0
        
        initial_data.update({
            'malzeme': siparis.teklif.malzeme, 
            'miktar': siparis.teslim_edilen - cikis_toplami
        })
        if s:=Depo.objects.filter(is_sanal=True).first(): initial_data['kaynak_depo'] = s
        if f:=Depo.objects.filter(is_sanal=False).first(): initial_data['hedef_depo'] = f

    if request.method == 'POST':
        form = DepoTransferForm(request.POST)
        if form.is_valid():
            transfer = form.save(commit=False)
            
            # Stok kontrolü
            kaynak_stok = transfer.malzeme.depo_stogu(transfer.kaynak_depo.id)
            if transfer.miktar > kaynak_stok:
                messages.error(request, f"⛔ Kaynak depoda yeterli stok yok! Mevcut: {kaynak_stok}")
                return redirect(f"{request.path}?siparis_id={siparis_id}" if siparis_id else request.path)
            
            if siparis:
                transfer.bagli_siparis = siparis
                
            transfer.save() # Sinyaller üzerinden StockService'i tetikler
            messages.success(request, "✅ Transfer başarıyla kaydedildi.")
            return redirect('siparis_listesi') if siparis else redirect('stok_listesi')
    else:
        form = DepoTransferForm(initial=initial_data)
        
    return render(request, 'depo_transfer.html', {'form': form, 'siparis': siparis})

@login_required
def stok_hareketleri(request, malzeme_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']): 
        return redirect('erisim_engellendi')
    malzeme = get_object_or_404(Malzeme, id=malzeme_id)
    hareketler = DepoHareket.objects.filter(malzeme_id=malzeme_id).order_by('-tarih')
    return render(request, 'stok_hareketleri.html', {'malzeme': malzeme, 'hareketler': hareketler})

@login_required
def get_depo_stok(request):
    try:
        mal_id = request.GET.get('malzeme_id')
        depo_id = request.GET.get('depo_id')
        if mal_id and depo_id:
            stok = Malzeme.objects.get(id=mal_id).depo_stogu(depo_id)
            return JsonResponse({'stok': float(stok)})
        return JsonResponse({'stok': 0})
    except Exception as e:
        return JsonResponse({'stok': 0})

@login_required
def stok_rontgen(request, malzeme_id):
    if not request.user.is_superuser: return HttpResponse("Yetkisiz")
    h = DepoHareket.objects.filter(malzeme_id=malzeme_id).order_by('tarih', 'id')
    html = "<table border='1'><tr><th>ID</th><th>İşlem</th><th>Depo</th><th>Miktar</th></tr>" + \
           "".join([f"<tr><td>{x.id}</td><td>{x.get_islem_turu_display()}</td><td>{x.depo.isim if x.depo else '-'}</td><td>{x.miktar}</td></tr>" for x in h]) + "</table>"
    return HttpResponse(html)

@login_required
def envanter_raporu(request):
    """
    PERFORMANS OPTİMİZASYONU: Uzman raporu uyarınca Group By (annotate) kullanılmıştır.
    Kullanım/Sarf depolarına giren malzemeler 'harcanmış' sayılır ve raporda görünmez.
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI', 'MUHASEBE_FINANS']): 
        return redirect('erisim_engellendi')
    
    # 1. KRİTİK FİLTRE: Sadece kullanım yeri OLMAYAN (is_kullanim_yeri=False) depoların stoklarını getir
    # Böylece Şantiye'ye (Kullanım yeri) giden 180 adet otomatik olarak 'yok' sayılır.
    stok_verileri = DepoHareket.objects.filter(
        depo__is_kullanim_yeri=False
    ).values('depo_id', 'malzeme_id').annotate(
        toplam_stok=Coalesce(Sum('miktar', filter=Q(islem_turu='giris')), Value(0, output_field=DecimalField())) - 
                    Coalesce(Sum('miktar', filter=Q(islem_turu='cikis')), Value(0, output_field=DecimalField())) -
                    Coalesce(Sum('miktar', filter=Q(islem_turu='iade')), Value(0, output_field=DecimalField()))
    ).filter(toplam_stok__gt=0) # Sadece gerçek stoğu kalanları listele

    # 2. Modelleri tek seferde hafızaya al (N+1 Query problemini önlemek için)
    depo_map = {d.id: d for d in Depo.objects.all()}
    malzeme_map = {m.id: m for m in Malzeme.objects.all()}

    # 3. Veriyi şablonun beklediği hiyerarşik yapıya dönüştür
    rapor_dict = {}
    for veri in stok_verileri:
        d_id = veri['depo_id']
        m_id = veri['malzeme_id']
        stok_miktari = veri['toplam_stok']

        if d_id not in rapor_dict:
            rapor_dict[d_id] = {'depo': depo_map.get(d_id), 'stoklar': []}
        
        rapor_dict[d_id]['stoklar'].append({
            'malzeme': malzeme_map.get(m_id),
            'miktar': stok_miktari
        })

    rapor_data = list(rapor_dict.values())
            
    return render(request, 'envanter_raporu.html', {'rapor_data': rapor_data})