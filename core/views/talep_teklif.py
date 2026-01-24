import json
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import transaction

from core.models import MalzemeTalep, Teklif, Malzeme, IsKalemi, SatinAlma
from core.forms import TalepForm, TeklifForm
from core.utils import tcmb_kur_getir
from core.services.finans_payments import PaymentService
from .guvenlik import yetki_kontrol


@login_required
def icmal_raporu(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    talepler_query = MalzemeTalep.objects.filter(
        durum__in=['bekliyor', 'islemde', 'onaylandi']
    ).select_related(
        'malzeme', 'is_kalemi', 'talep_eden'
    ).prefetch_related(
        'teklifler', 'teklifler__tedarikci'
    ).order_by(
        '-oncelik', '-tarih'
    )

    aktif_talepler = list(talepler_query)
    for talep in aktif_talepler:
        teklifler = talep.teklifler.all()
        if teklifler:
            try:
                en_uygun = min(teklifler, key=lambda t: t.toplam_fiyat_tl)
                talep.en_uygun_teklif_id = en_uygun.id
            except ValueError:
                pass

    context = {'aktif_talepler': aktif_talepler}
    return render(request, 'icmal.html', context)


@login_required
def talep_olustur(request):
    if request.method == 'POST':
        form = TalepForm(request.POST)
        if form.is_valid():
            talep = form.save(commit=False)
            talep.talep_eden = request.user
            talep.durum = 'bekliyor'
            talep.save()

            talep_adi = talep.malzeme.isim if talep.malzeme else (talep.is_kalemi.isim if talep.is_kalemi else "Yeni Talep")
            messages.success(request, f"✅ {talep_adi} talebiniz oluşturuldu ve satınalma ekranına düştü.")
            return redirect('icmal_raporu')
        else:
            messages.error(request, "Lütfen alanları kontrol ediniz.")
    else:
        form = TalepForm()
    return render(request, 'talep_olustur.html', {'form': form})


@login_required
def teklif_ekle(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'YONETICI']):
        return redirect('erisim_engellendi')

    talep_id = request.GET.get('talep_id')
    secili_talep = None
    initial_data = {}

    if talep_id:
        secili_talep = get_object_or_404(MalzemeTalep, id=talep_id)
        # Miktarın forma dolmasını sağlayan sözlük yapısı
        initial_data = {
            'talep': secili_talep.id,
            'miktar': secili_talep.miktar,
            'malzeme': secili_talep.malzeme,
            'is_kalemi': secili_talep.is_kalemi,
        }
        # KDV oranını talebe göre başlangıçta seçili getir
        if secili_talep.malzeme:
            initial_data['kdv_orani_secimi'] = secili_talep.malzeme.kdv_orani
        elif secili_talep.is_kalemi:
            initial_data['kdv_orani_secimi'] = secili_talep.is_kalemi.kdv_orani

    guncel_kurlar = tcmb_kur_getir()
    kurlar_dict = {k: float(v) for k, v in guncel_kurlar.items()}
    kurlar_dict['TRY'] = 1.0
    kurlar_json = json.dumps(kurlar_dict)

    malzeme_kdv_map = {m.id: m.kdv_orani for m in Malzeme.objects.all()}
    hizmet_kdv_map = {h.id: h.kdv_orani for h in IsKalemi.objects.all()}

    if request.method == 'POST':
        form = TeklifForm(request.POST, request.FILES)
        if form.is_valid():
            teklif = form.save(commit=False)

            if talep_id:
                teklif.talep = secili_talep
                if secili_talep.malzeme:
                    teklif.malzeme = secili_talep.malzeme
                if secili_talep.is_kalemi:
                    teklif.is_kalemi = secili_talep.is_kalemi

            # KDV ve Kur değerlerini işle
            if form.cleaned_data.get('kdv_orani_secimi'):
                try:
                    teklif.kdv_orani = int(form.cleaned_data['kdv_orani_secimi'])
                except Exception:
                    pass

            # Kur: teklif aşamasında yardımcı (asıl kilit onay anında)
                        # Kur: teklif kaydında DOĞRU kur_degeri mutlaka yazılmalı.
            # Çünkü PaymentService onay anında önce teklif.kur_degeri'ni "Manual/Existing" kabul ediyor.
            try:
                pb = (teklif.para_birimi or "TRY").upper().strip()
                if pb in ("TL", "", None):
                    pb = "TRY"

                if pb == "TRY":
                    teklif.kur_degeri = Decimal("1.0000")
                else:
                    # TCMB kurunu al (teklif giriş ekranında zaten bunu gösteriyorsun)
                    kur = guncel_kurlar.get(pb)

                    # Kur yoksa ONAY SÜRECİNİ BOZAR; burada hata verelim.
                    if kur is None:
                        messages.error(request, f"❌ {pb} için TCMB kuru bulunamadı. Lütfen tekrar deneyin.")
                        return render(request, 'teklif_ekle.html', {
                            'form': form,
                            'kurlar_json': kurlar_json,
                            'guncel_kurlar': guncel_kurlar,
                            'secili_talep': secili_talep,
                            'malzeme_kdv_json': json.dumps(malzeme_kdv_map),
                            'hizmet_kdv_json': json.dumps(hizmet_kdv_map),
                        })

                    teklif.kur_degeri = Decimal(str(kur))
            except Exception:
                # Güvenli fallback: TRY harici para biriminde 1'e düşmek yerine hata vermek daha doğru.
                pb = (teklif.para_birimi or "TRY").upper().strip()
                if pb not in ("TRY", "TL", "", None):
                    messages.error(request, "❌ Kur hesaplanamadı. Lütfen tekrar deneyin.")
                    return render(request, 'teklif_ekle.html', {
                        'form': form,
                        'kurlar_json': kurlar_json,
                        'guncel_kurlar': guncel_kurlar,
                        'secili_talep': secili_talep,
                        'malzeme_kdv_json': json.dumps(malzeme_kdv_map),
                        'hizmet_kdv_json': json.dumps(hizmet_kdv_map),
                    })
                teklif.kur_degeri = Decimal("1.0000")

            teklif.save()
            messages.success(request, "✅ Teklif başarıyla kaydedildi.")
            return redirect('icmal_raporu')
        else:
            messages.error(request, "Lütfen formdaki hataları düzeltiniz.")
    else:
        # Formu başlangıç verileriyle (miktar dahil) başlat
        form = TeklifForm(initial=initial_data)

    context = {
        'form': form,
        'kurlar_json': kurlar_json,
        'guncel_kurlar': guncel_kurlar,
        'secili_talep': secili_talep,
        'malzeme_kdv_json': json.dumps(malzeme_kdv_map),
        'hizmet_kdv_json': json.dumps(hizmet_kdv_map),
    }
    return render(request, 'teklif_ekle.html', context)


@login_required
def teklif_durum_guncelle(request, teklif_id, yeni_durum):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'YONETICI']):
        return redirect('erisim_engellendi')

    teklif = get_object_or_404(Teklif, id=teklif_id)

    # MANTIK HATASI DÜZELTME: Çift onay kontrolü
    if yeni_durum == 'onaylandi':
        if teklif.talep:
            zaten_onayli_var_mi = Teklif.objects.filter(
                talep=teklif.talep,
                durum='onaylandi'
            ).exclude(id=teklif.id).exists()

            if zaten_onayli_var_mi:
                messages.error(request, "❌ HATA: Bu talebe ait başka bir teklif zaten onaylanmış! İkinci bir onaya izin verilmez.")
                referer = request.META.get('HTTP_REFERER')
                return redirect(referer) if referer else redirect('icmal_raporu')

        # Onay süreci işlemleri:
        # - transaction + select_for_update: paralel isteklerde çakışmayı engeller
        # - kur kilitleme: onay anında TL toplamlar locked_* alanlarına yazılır (tek gerçek kaynak)
        with transaction.atomic():
            teklif = Teklif.objects.select_for_update().get(id=teklif.id)

            # Talep durumunu güncelle
            if teklif.talep:
                teklif.talep.durum = 'onaylandi'
                teklif.talep.save(update_fields=["durum"])

            # ✅ Onay anında TL kilitle
            PaymentService.teklif_onayinda_tl_sabitle(teklif)

            # Siparişi oluştur (varsa dokunma)
            SatinAlma.objects.get_or_create(
                teklif=teklif,
                defaults={
                    'toplam_miktar': teklif.miktar,
                    'teslim_edilen': 0,
                    'siparis_tarihi': timezone.now()
                }
            )

    teklif.durum = yeni_durum
    teklif.save(update_fields=["durum"])

    messages.success(request, f"Teklif durumu '{yeni_durum}' olarak güncellendi.")
    referer = request.META.get('HTTP_REFERER')
    return redirect(referer) if referer else redirect('icmal_raporu')


@login_required
def talep_onayla(request, talep_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    talep = get_object_or_404(MalzemeTalep, id=talep_id)
    if talep.durum == 'bekliyor':
        talep.durum = 'islemde'
        talep.onay_tarihi = timezone.now()
        talep.save(update_fields=["durum", "onay_tarihi"])

        talep_adi = talep.malzeme.isim if talep.malzeme else talep.is_kalemi.isim
        messages.success(request, f"✅ Talep onaylandı: {talep_adi} için teklif süreci başladı.")
    return redirect('icmal_raporu')


@login_required
def talep_tamamla(request, talep_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'YONETICI']):
        return redirect('erisim_engellendi')

    talep = get_object_or_404(MalzemeTalep, id=talep_id)
    talep_adi = talep.malzeme.isim if talep.malzeme else talep.is_kalemi.isim

    if talep.durum == 'onaylandi':
        talep.durum = 'tamamlandi'
        talep.temin_tarihi = timezone.now()
        talep.save(update_fields=["durum", "temin_tarihi"])
        messages.success(request, f"📦 {talep_adi} talebi arşivlendi ve listeden kaldırıldı.")
    return redirect('icmal_raporu')


@login_required
def talep_sil(request, talep_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'YONETICI']):
        messages.error(request, "Silme yetkiniz yok!")
        return redirect('icmal_raporu')

    talep = get_object_or_404(MalzemeTalep, id=talep_id)
    talep_adi = talep.malzeme.isim if talep.malzeme else talep.is_kalemi.isim
    talep.delete()
    messages.warning(request, f"🗑️ {talep_adi} talebi silindi.")
    return redirect('icmal_raporu')


@login_required
def arsiv_raporu(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    arsiv_talepler = MalzemeTalep.objects.filter(
        durum='tamamlandi'
    ).select_related(
        'malzeme', 'talep_eden', 'is_kalemi'
    ).prefetch_related(
        'teklifler__tedarikci'
    ).order_by(
        '-temin_tarihi', '-tarih'
    )

    context = {'aktif_talepler': arsiv_talepler, 'arsiv_modu': True}
    return render(request, 'icmal.html', context)


@login_required
def talep_arsivden_cikar(request, talep_id):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'YONETICI']):
        return redirect('erisim_engellendi')

    talep = get_object_or_404(MalzemeTalep, id=talep_id)
    if talep.durum == 'tamamlandi':
        talep.durum = 'onaylandi'
        talep.save(update_fields=["durum"])
        messages.success(request, f"♻️ {talep.malzeme.isim if talep.malzeme else talep.is_kalemi.isim} arşivden çıkarıldı.")
    return redirect('arsiv_raporu')