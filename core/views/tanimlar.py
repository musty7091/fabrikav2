from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.models import Tedarikci, Malzeme, IsKalemi, Kategori, Depo, Teklif, MalzemeTalep, DepoHareket, SatinAlma
from core.forms import TedarikciForm, MalzemeForm, IsKalemiForm, KategoriForm, DepoForm
from .guvenlik import yetki_kontrol

@login_required
def tanim_yonetimi(request):
    return render(request, 'tanim_yonetimi.html') if yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'SAHA_VE_DEPO', 'YONETICI']) else redirect('erisim_engellendi')

def crud_view(request, model_class, form_class, template, redirect_url, pk=None, silme=False):
    # Generic CRUD Helper
    if not yetki_kontrol(request.user, ['OFIS_VE_SATINALMA', 'YONETICI', 'SAHA_VE_DEPO']): return redirect('erisim_engellendi')
    obj = get_object_or_404(model_class, pk=pk) if pk else None
    
    if silme:
        if not yetki_kontrol(request.user, ['YONETICI']): messages.error(request, "Yetkisiz işlem."); return redirect(redirect_url)
        try: obj.delete(); messages.warning(request, f"🗑️ Kayıt silindi.")
        except: messages.error(request, "⛔ Bu kayıt kullanımda olduğu için silinemez!")
        return redirect(redirect_url)

    if request.method == 'POST':
        form = form_class(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, f"✅ İşlem başarılı.")
            return redirect(redirect_url)
    else:
        form = form_class(instance=obj)
    return render(request, template, {'form': form, 'duzenleme_modu': pk is not None})

# Wrapper Functions
@login_required
def tedarikci_listesi(request): return render(request, 'tedarikci_listesi.html', {'tedarikciler': Tedarikci.objects.order_by('firma_unvani')})
@login_required
def tedarikci_ekle(request): return crud_view(request, Tedarikci, TedarikciForm, 'tedarikci_ekle.html', 'tedarikci_ekle' if request.path.endswith('ekle/') else 'tedarikci_listesi')
@login_required
def tedarikci_duzenle(request, pk): return crud_view(request, Tedarikci, TedarikciForm, 'tedarikci_ekle.html', 'tedarikci_listesi', pk)
@login_required
def tedarikci_sil(request, pk): return crud_view(request, Tedarikci, None, None, 'tedarikci_listesi', pk, silme=True)

@login_required
def malzeme_ekle(request): return crud_view(request, Malzeme, MalzemeForm, 'malzeme_ekle.html', 'stok_listesi')
@login_required
def malzeme_duzenle(request, pk): return crud_view(request, Malzeme, MalzemeForm, 'malzeme_ekle.html', 'stok_listesi', pk)
@login_required
def malzeme_sil(request, pk): return crud_view(request, Malzeme, None, None, 'stok_listesi', pk, silme=True)

@login_required
def hizmet_listesi(request): return render(request, 'hizmet_listesi.html', {'hizmetler': IsKalemi.objects.all()})
@login_required
def hizmet_ekle(request): return crud_view(request, IsKalemi, IsKalemiForm, 'hizmet_ekle.html', 'hizmet_listesi')
@login_required
def hizmet_duzenle(request, pk): return crud_view(request, IsKalemi, IsKalemiForm, 'hizmet_ekle.html', 'hizmet_listesi', pk)
@login_required
def hizmet_sil(request, pk): return crud_view(request, IsKalemi, None, None, 'hizmet_listesi', pk, silme=True)

@login_required
def kategori_listesi(request): return render(request, 'kategori_listesi.html', {'kategoriler': Kategori.objects.all()})
@login_required
def kategori_ekle(request): return crud_view(request, Kategori, KategoriForm, 'kategori_ekle.html', 'tanim_yonetimi')
@login_required
def kategori_duzenle(request, pk): return crud_view(request, Kategori, KategoriForm, 'kategori_ekle.html', 'kategori_listesi', pk)
@login_required
def kategori_sil(request, pk): return crud_view(request, Kategori, None, None, 'kategori_listesi', pk, silme=True)

@login_required
def depo_listesi(request): return render(request, 'depo_listesi.html', {'depolar': Depo.objects.all()})
@login_required
def depo_ekle(request): return crud_view(request, Depo, DepoForm, 'depo_ekle.html', 'tanim_yonetimi')
@login_required
def depo_duzenle(request, pk): return crud_view(request, Depo, DepoForm, 'depo_ekle.html', 'depo_listesi', pk)
@login_required
def depo_sil(request, pk): return crud_view(request, Depo, None, None, 'depo_listesi', pk, silme=True)