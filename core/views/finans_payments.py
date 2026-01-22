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
        last_dot = value_str.rfind('.')
        last_comma = value_str.rfind(',')

        if last_comma > last_dot:
            # Format: 1.250,50 (TR)
            value_str = value_str.replace('.', '').replace(',', '.')
        else:
            # Format: 1,250.50 (US)
            value_str = value_str.replace(',', '')
    elif ',' in value_str:
        value_str = value_str.replace(',', '.')

    try:
        return Decimal(value_str)
    except (InvalidOperation, ValueError):
        return Decimal('0.00')


def _pick_attr(obj, names):
    """Objede listelenen alan adlarından ilk bulunanı döndürür (yoksa None)."""
    for n in names:
        if hasattr(obj, n):
            val = getattr(obj, n)
            if val not in [None, ""]:
                return val
    return None


def _normalize_currency(pb):
    if not pb:
        return "TRY"
    pb = str(pb).strip().upper()
    if pb == "TL":
        return "TRY"
    return pb


def get_smart_exchange_rate(obj, guncel_kurlar):
    """
    Fatura veya Hakediş için doğru kuru ve para birimini bulur.
    Öncelik sırası:
      1) Objede direkt para_birimi ve kur alanları (varsa)
      2) Objede TL karşılığı alanı varsa -> kur türet
      3) Satınalma -> teklif üzerinden para birimi/kur
      4) En son TCMB güncel kuru
    Dönüş: (para_birimi, kur_degeri)
    """
    pb = "TRY"
    kur = Decimal("1.0")

    # --- 1) Objede direkt para birimi var mı? ---
    direct_pb = _pick_attr(obj, ["para_birimi", "currency", "doviz_cinsi", "doviz"])
    if direct_pb:
        pb = _normalize_currency(direct_pb)

    # Satınalma/teklif üzerinden pb yakalama (mevcut mantığın korunmuş hali)
    if pb == "TRY":
        if hasattr(obj, 'satinalma') and obj.satinalma and getattr(obj.satinalma, "teklif", None):
            pb = _normalize_currency(getattr(obj.satinalma.teklif, "para_birimi", "TRY"))

    # TRY ise kur 1
    if pb in ["TRY"]:
        return "TRY", Decimal("1.0")

    # --- 2) Objede direkt kur alanı var mı? ---
    direct_kur = _pick_attr(obj, ["kur_degeri", "kur", "fx_rate", "doviz_kuru"])
    if direct_kur:
        try:
            k = to_decimal(direct_kur)
            if k > Decimal("0.1"):
                return pb, k
        except Exception:
            pass

    # --- 3) Objede TL karşılığı var mı? (kur türet) ---
    # Örn: fat.genel_toplam = 12000 (USD), fat.genel_toplam_tl = 520320 (TRY)
    # Bu varsa kur = tl / doviz
    # Not: Alan adlarını geniş tuttum; sende varsa otomatik yakalar.
    total_foreign = _pick_attr(obj, ["genel_toplam", "tutar", "net_tutar", "odenecek_net_tutar"])
    total_try = _pick_attr(obj, ["genel_toplam_tl", "tutar_tl", "tl_karsiligi", "try_karsiligi", "toplam_tl"])

    try:
        tf = to_decimal(total_foreign) if total_foreign is not None else None
        tt = to_decimal(total_try) if total_try is not None else None
        if tf and tt and tf > Decimal("0.1") and tt > Decimal("0.1"):
            derived = tt / tf
            if derived > Decimal("0.1"):
                return pb, derived
    except Exception:
        pass

    # --- 4) Satınalma/teklif üzerinden kur yakala ---
    if hasattr(obj, 'satinalma') and obj.satinalma and getattr(obj.satinalma, "teklif", None):
        teklif = obj.satinalma.teklif
        teklif_kur = _pick_attr(teklif, ["kur_degeri", "kur", "fx_rate"])
        if teklif_kur:
            try:
                k = to_decimal(teklif_kur)
                if k > Decimal("0.1"):
                    return pb, k
            except Exception:
                pass

    # --- 5) En son: TCMB güncel kur ---
    try:
        k = guncel_kurlar.get(pb, Decimal("1.0"))
        k = to_decimal(k)
        if k > Decimal("0.1"):
            return pb, k
    except Exception:
        pass

    return pb, Decimal("1.0")


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
                    pb, kur = get_smart_exchange_rate(hk, guncel_kurlar)
                    tl_karsiligi = kalan_orj * kur

                    aciklama = f"Hakediş #{hk.hakedis_no}"
                    try:
                        if hk.satinalma and hk.satinalma.teklif and hk.satinalma.teklif.is_kalemi:
                            aciklama += f" - {hk.satinalma.teklif.is_kalemi.isim}"
                    except:
                        pass

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

                raw_tutar = request.POST.get('tutar', '0')
                odeme.tutar = clean_currency_input(raw_tutar)
                odeme.para_birimi = 'TRY'  # Her zaman TL
                odeme.save()
                
                if fatura_id and not odeme.fatura:
                    try:
                        odeme.fatura = Fatura.objects.get(id=int(fatura_id))
                        odeme.save(update_fields=["fatura"])
                    except Exception:
                        pass

                dagitilacak_tl = odeme.tutar
                secilenler = request.POST.getlist('secilen_kalem')

                if not secilenler and fatura_id:
                    secilenler = [f"Fatura_{fatura_id}"]

                for secim in secilenler:
                    if dagitilacak_tl <= 0:
                        break
                    try:
                        tip, id_str = secim.split('_')
                        obj_id = int(id_str)
                    except ValueError:
                        continue

                    if tip == 'Hakedis':
                        hk = Hakedis.objects.get(id=obj_id)
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

                        _, kur = get_smart_exchange_rate(fat, guncel_kurlar)
                        odenen_orj = dagitilacak_tl / kur if kur > 0 else dagitilacak_tl

                        if hasattr(fat, 'odenen_tutar'):
                            mevcut = to_decimal(getattr(fat, 'odenen_tutar', 0))
                            fat.odenen_tutar = mevcut + odenen_orj
                            if fat.odenen_tutar >= (to_decimal(fat.genel_toplam) - Decimal('0.5')):
                                if hasattr(fat, 'durum'):
                                    fat.durum = 'odendi'
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
    (Dövizli faturada genel_toplam döviz ise, TL karşılığı artık yanlış çıkmayacak.)
    """
    tedarikci = get_object_or_404(Tedarikci, id=tedarikci_id)
    hareketler = []
    guncel_kurlar = tcmb_kur_getir()

    # 1. FATURALAR
    for fat in Fatura.objects.filter(tedarikci=tedarikci):
        pb, kur = get_smart_exchange_rate(fat, guncel_kurlar)

        genel_toplam = to_decimal(fat.genel_toplam)

        # 🔴 KRİTİK DÜZELTME
        # Eğer pb TRY görünüyorsa ama faturaya yapılan TL ödeme,
        # fatura tutarından çok büyükse → bu fatura dövizlidir
        if pb == "TRY":
            odenen_tl = (
                Odeme.objects.filter(fatura=fat)
                .aggregate(toplam=Sum("tutar"))["toplam"]
                or Decimal("0")
            )

            if odenen_tl > genel_toplam * Decimal("1.5"):
                # Bu bir döviz faturası → kur türet
                kur = odenen_tl / genel_toplam
                pb = "USD"  # veya istersen "DÖVİZ" yaz
                

        tl_borc = genel_toplam * kur

        aciklama = f"Fatura #{fat.fatura_no}"
        if pb != 'TRY':
            aciklama += f"<br><span class='badge bg-light text-dark border'>Orj: {to_decimal(fat.genel_toplam):,.2f} {pb} | Kur: {kur}</span>"

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
        tl_borc = to_decimal(hk.odenecek_net_tutar) * to_decimal(kur)

        aciklama = f"Hakediş #{hk.hakedis_no}"
        if pb != 'TRY':
            aciklama += f"<br><span class='badge bg-light text-dark border'>Orj: {to_decimal(hk.odenecek_net_tutar):,.2f} {pb} | Kur: {kur}</span>"

        hareketler.append({
            'tarih': hk.tarih,
            'aciklama': aciklama,
            'borc': tl_borc,
            'alacak': Decimal('0'),
            'tip': 'hakedis'
        })

    # 3. ÖDEMELER (zaten TL kaydediyorsun)
    for o in Odeme.objects.filter(tedarikci=tedarikci):
        tl_alacak = to_decimal(o.tutar)
        aciklama = f"Ödeme ({o.get_odeme_turu_display()})"
        if o.aciklama:
            aciklama += f" - {o.aciklama}"

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
    """
    KRİTİK DÜZELTME:
    fat.odenen_tutar senin sisteminde döviz (orj) tutuluyor (odeme_yap içinde odenen_orj ekliyorsun).
    Ama burada TL'yi direkt düşüyordun. Bu yanlış.
    Doğru olan: TL'yi kur ile dövize çevirip düşmek.
    """
    if not yetki_kontrol(request.user, ['MUHASEBE_FINANS', 'YONETICI']):
        return redirect('erisim_engellendi')

    odeme = get_object_or_404(Odeme, id=odeme_id)

    if odeme.fatura and hasattr(odeme.fatura, 'odenen_tutar'):
        fat = odeme.fatura
        guncel_kurlar = tcmb_kur_getir()
        _, kur = get_smart_exchange_rate(fat, guncel_kurlar)

        # TL ödeme -> dövize çevir
        odenen_orj = to_decimal(odeme.tutar) / to_decimal(kur) if to_decimal(kur) > 0 else to_decimal(odeme.tutar)

        yeni = to_decimal(fat.odenen_tutar) - odenen_orj
        fat.odenen_tutar = max(yeni, Decimal('0'))

        # Durum varsa geri çek
        if hasattr(fat, 'durum'):
            try:
                if to_decimal(fat.odenen_tutar) < (to_decimal(fat.genel_toplam) - Decimal('0.5')):
                    fat.durum = 'acik'
            except Exception:
                pass

        fat.save()

    odeme.delete()
    messages.warning(request, "🗑️ Ödeme kaydı silindi.")
    return redirect('finans_dashboard')
