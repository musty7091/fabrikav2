from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from django.shortcuts import render, redirect, get_object_or_404

from core.models import Harcama
from core.forms.harcama import HarcamaForm


@login_required
def gider_listesi(request):
    """
    Harcama listesini TL karşılığıyla birlikte gösterir.
    tl_tutar bir @property olduğu için DB'de toplanamaz;
    bu yüzden tutar * kur_degeri olarak annotate ederiz.
    """
    qs = (
        Harcama.objects
        .select_related("kategori")
        .annotate(
            tl=ExpressionWrapper(
                F("tutar") * F("kur_degeri"),
                output_field=DecimalField(max_digits=20, decimal_places=2)
            )
        )
        .order_by("-tarih")
    )

    toplam_tl = qs.aggregate(s=Sum("tl"))["s"] or Decimal("0.00")

    # Kategori bazlı dağılım (grafik/özet için)
    kategori_ozet = (
        Harcama.objects
        .select_related("kategori")
        .annotate(
            tl=ExpressionWrapper(
                F("tutar") * F("kur_degeri"),
                output_field=DecimalField(max_digits=20, decimal_places=2)
            )
        )
        .values("kategori__isim")
        .annotate(toplam=Sum("tl"))
        .order_by("-toplam")
    )

    return render(request, "gider_listesi.html", {
        "giderler": qs,
        "toplam_tl": toplam_tl,
        "kategori_ozet": kategori_ozet,
    })


@login_required
def gider_ekle(request):
    if request.method == "POST":
        form = HarcamaForm(request.POST, request.FILES)
        if form.is_valid():
            gider = form.save()  # Nesneyi değişkene atıyoruz
            messages.success(request, "✅ Gider kaydedildi.")
            
            # DEĞİŞEN KISIM: Yazdırma onayı sayfasına yönlendir
            return redirect('islem_sonuc', model_name='harcama', pk=gider.id)
    else:
        form = HarcamaForm()

    return render(request, "gider_ekle.html", {"form": form})


@login_required
def gider_duzenle(request, pk: int):
    obj = get_object_or_404(Harcama, pk=pk)

    if request.method == "POST":
        form = HarcamaForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Gider güncellendi.")
            return redirect("gider_listesi")
    else:
        form = HarcamaForm(instance=obj)

    return render(request, "gider_ekle.html", {"form": form, "edit_mode": True, "obj": obj})
