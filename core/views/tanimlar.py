from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.forms import DepoForm, IsKalemiForm, KategoriForm, MalzemeForm, TedarikciForm
from core.models import Depo, IsKalemi, Kategori, Malzeme, Tedarikci
from .guvenlik import yetki_kontrol


# ==========================================================
# TANIM YÖNETİMİ (Menü)
# ==========================================================

@login_required
def tanim_yonetimi(request):
    # Menü ekranı
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')
    return render(request, 'tanim_yonetimi.html')


# ==========================================================
# ORTAK YARDIMCILAR
# ==========================================================

def _durum_filtrele(request, qs):
    """
    Tanım listelerinde aktif/pasif/hepsi filtreleme.
    GET param: ?durum=aktif|pasif|hepsi
    """
    durum = (request.GET.get('durum') or 'aktif').lower().strip()
    if durum == 'pasif':
        qs = qs.filter(is_active=False)
    elif durum == 'hepsi':
        qs = qs
    else:
        durum = 'aktif'
        qs = qs.filter(is_active=True)
    return durum, qs


def _back_or(default_url_name: str):
    """
    Referer varsa oraya, yoksa default url'e dön.
    """
    def _inner(request):
        ref = request.META.get('HTTP_REFERER')
        if ref:
            return redirect(ref)
        return redirect(default_url_name)
    return _inner


def _crud_view(request, model_class, form_class, template: str, redirect_url_name: str, pk: int | None = None):
    """
    Basit create/update helper. (POST -> redirect, GET -> render)
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'YONETICI', 'SAHA_VE_DEPO']):
        return redirect('erisim_engellendi')

    obj = get_object_or_404(model_class, pk=pk) if pk else None

    if request.method == 'POST':
        form = form_class(request.POST, instance=obj)
        if form.is_valid():
            saved = form.save()
            if pk:
                messages.success(request, "✅ Kayıt güncellendi.")
            else:
                messages.success(request, "✅ Kayıt eklendi.")
            return redirect(redirect_url_name)
        messages.error(request, "⛔ Form hatalı. Lütfen alanları kontrol edin.")
    else:
        form = form_class(instance=obj)

    return render(request, template, {'form': form, 'duzenleme_modu': pk is not None})


@require_POST
@login_required
def tanim_toggle_active(request, model: str, pk: int):
    """
    Soft delete/restore (is_active toggle).
    URL: /tanim/toggle/<model>/<pk>/
    model: tedarikci|depo|kategori|malzeme|hizmet
    """
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'YONETICI', 'SAHA_VE_DEPO']):
        return redirect('erisim_engellendi')

    model_map = {
        'tedarikci': (Tedarikci, 'Tedarikçi'),
        'depo': (Depo, 'Depo'),
        'kategori': (Kategori, 'Kategori'),
        'malzeme': (Malzeme, 'Malzeme'),
        'hizmet': (IsKalemi, 'Hizmet/İş Kalemi'),
    }

    if model not in model_map:
        messages.error(request, "⛔ Geçersiz tanım tipi.")
        return redirect('tanim_yonetimi')

    cls, label = model_map[model]
    obj = get_object_or_404(cls, pk=pk)

    obj.is_active = not bool(obj.is_active)
    obj.save(update_fields=['is_active'])

    if obj.is_active:
        messages.success(request, f"✅ {label} tekrar AKTİF edildi.")
    else:
        messages.warning(request, f"🟡 {label} PASİF edildi. (Silinmedi)")

    # referer varsa oraya dön
    ref = request.META.get('HTTP_REFERER')
    if ref:
        return redirect(ref)

    # yoksa mantıklı listeye
    fallback = {
        'tedarikci': 'tedarikci_listesi',
        'depo': 'depo_listesi',
        'kategori': 'kategori_listesi',
        'malzeme': 'stok_listesi',
        'hizmet': 'hizmet_listesi',
    }[model]
    return redirect(fallback)


# ==========================================================
# TEDARİKÇİ CRUD
# ==========================================================

@login_required
def tedarikci_listesi(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')

    qs = Tedarikci.objects.order_by('firma_unvani')
    durum, qs = _durum_filtrele(request, qs)

    return render(request, 'tedarikci_listesi.html', {
        'tedarikciler': qs,
        'durum': durum,
    })


@login_required
def tedarikci_ekle(request):
    return _crud_view(request, Tedarikci, TedarikciForm, 'tedarikci_ekle.html', 'tedarikci_listesi')


@login_required
def tedarikci_duzenle(request, pk):
    return _crud_view(request, Tedarikci, TedarikciForm, 'tedarikci_ekle.html', 'tedarikci_listesi', pk)


# Eski URL ismi kalsın (kırılma olmasın): artık "sil" => pasif et
@login_required
def tedarikci_sil(request, pk):
    if request.method != 'POST':
        # Güvenlik için: silme/pasif etme işlemi GET ile yapılmasın
        messages.error(request, "⛔ Geçersiz istek.")
        return redirect('tedarikci_listesi')
    return tanim_toggle_active(request, 'tedarikci', pk)


# ==========================================================
# MALZEME CRUD (liste: stok_listesi ayrı view'de)
# ==========================================================

@login_required
def malzeme_ekle(request):
    return _crud_view(request, Malzeme, MalzemeForm, 'malzeme_ekle.html', 'stok_listesi')


@login_required
def malzeme_duzenle(request, pk):
    return _crud_view(request, Malzeme, MalzemeForm, 'malzeme_ekle.html', 'stok_listesi', pk)


@login_required
def malzeme_sil(request, pk):
    if request.method != 'POST':
        messages.error(request, "⛔ Geçersiz istek.")
        return redirect('stok_listesi')
    return tanim_toggle_active(request, 'malzeme', pk)


# ==========================================================
# HİZMET / İŞ KALEMİ CRUD
# ==========================================================

@login_required
def hizmet_listesi(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')

    qs = IsKalemi.objects.select_related('kategori').order_by('kategori__isim', 'isim')
    durum, qs = _durum_filtrele(request, qs)

    return render(request, 'hizmet_listesi.html', {'hizmetler': qs, 'durum': durum})


@login_required
def hizmet_ekle(request):
    return _crud_view(request, IsKalemi, IsKalemiForm, 'hizmet_ekle.html', 'hizmet_listesi')


@login_required
def hizmet_duzenle(request, pk):
    return _crud_view(request, IsKalemi, IsKalemiForm, 'hizmet_ekle.html', 'hizmet_listesi', pk)


@login_required
def hizmet_sil(request, pk):
    if request.method != 'POST':
        messages.error(request, "⛔ Geçersiz istek.")
        return redirect('hizmet_listesi')
    return tanim_toggle_active(request, 'hizmet', pk)


# ==========================================================
# KATEGORİ CRUD
# ==========================================================

@login_required
def kategori_listesi(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')

    qs = Kategori.objects.order_by('isim')
    durum, qs = _durum_filtrele(request, qs)

    return render(request, 'kategori_listesi.html', {'kategoriler': qs, 'durum': durum})


@login_required
def kategori_ekle(request):
    return _crud_view(request, Kategori, KategoriForm, 'kategori_ekle.html', 'kategori_listesi')


@login_required
def kategori_duzenle(request, pk):
    return _crud_view(request, Kategori, KategoriForm, 'kategori_ekle.html', 'kategori_listesi', pk)


@login_required
def kategori_sil(request, pk):
    if request.method != 'POST':
        messages.error(request, "⛔ Geçersiz istek.")
        return redirect('kategori_listesi')
    return tanim_toggle_active(request, 'kategori', pk)


# ==========================================================
# DEPO CRUD
# ==========================================================

@login_required
def depo_listesi(request):
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']):
        return redirect('erisim_engellendi')

    qs = Depo.objects.order_by('isim')
    durum, qs = _durum_filtrele(request, qs)

    return render(request, 'depo_listesi.html', {'depolar': qs, 'durum': durum})


@login_required
def depo_ekle(request):
    return _crud_view(request, Depo, DepoForm, 'depo_ekle.html', 'depo_listesi')


@login_required
def depo_duzenle(request, pk):
    return _crud_view(request, Depo, DepoForm, 'depo_ekle.html', 'depo_listesi', pk)


@login_required
def depo_sil(request, pk):
    if request.method != 'POST':
        messages.error(request, "⛔ Geçersiz istek.")
        return redirect('depo_listesi')
    return tanim_toggle_active(request, 'depo', pk)
