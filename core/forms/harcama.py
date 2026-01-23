from django import forms
from core.models import Harcama, GiderKategorisi

class HarcamaForm(forms.ModelForm):
    class Meta:
        model = Harcama
        fields = ["kategori", "aciklama", "tutar", "para_birimi", "kur_degeri", "tarih", "dekont"]
        widgets = {"tarih": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sadece aktif kategoriler
        self.fields["kategori"].queryset = GiderKategorisi.objects.filter(is_active=True).order_by("isim")