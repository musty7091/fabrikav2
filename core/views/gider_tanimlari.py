from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from core.models import GiderKategorisi


@login_required
def gider_tanim_listesi(request):
    filtre = request.GET.get("durum", "aktif")  # aktif | pasif | hepsi

    qs = GiderKategorisi.objects.all().order_by("isim")
    if filtre == "aktif":
        qs = qs.filter(is_active=True)
    elif filtre == "pasif":
        qs = qs.filter(is_active=False)

    return render(request, "gider_tanim_listesi.html", {
        "items": qs,
        "filtre": filtre,
    })


@login_required
def gider_tanim_ekle(request):
    if request.method == "POST":
        isim = (request.POST.get("isim") or "").strip()
        if not isim:
            messages.error(request, "Gider kategorisi adı zorunludur.")
            return render(request, "gider_tanim_form.html", {"mode": "create"})

        obj, created = GiderKategorisi.objects.get_or_create(isim=isim)
        if not created and not obj.is_active:
            obj.is_active = True
            obj.save(update_fields=["is_active"])
            messages.success(request, "Kategori zaten vardı; tekrar aktif edildi.")
        else:
            messages.success(request, "Gider kategorisi eklendi.")

        return redirect("gider_tanim_listesi")

    return render(request, "gider_tanim_form.html", {"mode": "create"})


@login_required
def gider_tanim_duzenle(request, pk: int):
    obj = get_object_or_404(GiderKategorisi, pk=pk)

    if request.method == "POST":
        isim = (request.POST.get("isim") or "").strip()
        if not isim:
            messages.error(request, "Gider kategorisi adı zorunludur.")
            return render(request, "gider_tanim_form.html", {"mode": "edit", "obj": obj})

        obj.isim = isim
        obj.save(update_fields=["isim"])
        messages.success(request, "Gider kategorisi güncellendi.")
        return redirect("gider_tanim_listesi")

    return render(request, "gider_tanim_form.html", {"mode": "edit", "obj": obj})


@login_required
def gider_tanim_toggle_active(request, pk: int):
    obj = get_object_or_404(GiderKategorisi, pk=pk)
    obj.is_active = not obj.is_active
    obj.save(update_fields=["is_active"])
    messages.success(request, f"Kategori {'aktif' if obj.is_active else 'pasif'} yapıldı.")
    return redirect("gider_tanim_listesi")
