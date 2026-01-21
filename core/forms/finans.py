# core/forms/finans.py
from django import forms
from django.forms import inlineformset_factory
from decimal import Decimal, InvalidOperation

from core.models import (
    Teklif, Fatura, FaturaKalem, Hakedis, Odeme, 
    KDV_ORANLARI, Depo
)

# Yardımcı Fonksiyon
def to_decimal(val, default="0"):
    if val is None or val == "":
        return Decimal(str(default))
    if isinstance(val, Decimal):
        return val
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    if isinstance(val, str):
        v = val.strip().replace(" ", "")
        # Eğer sadece nokta varsa (10.50) -> Decimal anlar
        # Eğer virgül varsa (10,50) -> Noktaya çevirip anlar
        # AMA (1.250,50) gelirse patlar. O yüzden clean metodunda özel işlem yapacağız.
        v = v.replace(",", ".")
        try:
            return Decimal(v)
        except InvalidOperation:
            return Decimal(str(default))
    return Decimal(str(default))

# ========================================================
# 1. TEKLİF FORMU
# ========================================================
class TeklifForm(forms.ModelForm):
    kdv_orani_secimi = forms.ChoiceField(
        choices=[('', 'Seçiniz...')] + list(KDV_ORANLARI),
        label="KDV Oranı",
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Teklif
        fields = [
            'talep', 'tedarikci', 'malzeme', 'is_kalemi',
            'miktar', 'birim_fiyat', 'para_birimi',
            'kdv_dahil_mi', 'teklif_dosyasi'
        ]
        widgets = {
            'talep': forms.HiddenInput(),
            'tedarikci': forms.Select(attrs={'class': 'form-select select2'}),
            'malzeme': forms.Select(attrs={'class': 'form-select'}),
            'is_kalemi': forms.Select(attrs={'class': 'form-select'}),
            'miktar': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'birim_fiyat': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'para_birimi': forms.Select(attrs={'class': 'form-select'}),
            'kdv_dahil_mi': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'teklif_dosyasi': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        malzeme = cleaned_data.get('malzeme')
        is_kalemi = cleaned_data.get('is_kalemi')

        if not malzeme and not is_kalemi:
            raise forms.ValidationError("Lütfen ya bir Malzeme ya da bir İş Kalemi seçiniz.")
        if malzeme and is_kalemi:
            raise forms.ValidationError("Hem malzeme hem hizmet seçemezsiniz. Sadece birini seçin.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        secim = self.cleaned_data.get("kdv_orani_secimi")
        if secim not in (None, ""):
            try:
                instance.kdv_orani = int(secim)
            except (TypeError, ValueError):
                pass
        if commit:
            instance.save()
            self.save_m2m()
        return instance

# ========================================================
# 2. FATURA FORMLARI
# ========================================================

class FaturaGirisForm(forms.ModelForm):
    """
    SENARYO 1: Sipariş Faturası (Otomatik)
    """
    class Meta:
        model = Fatura
        fields = ["fatura_no", "tarih", "dosya", "aciklama"]
        widgets = {
            "fatura_no": forms.TextInput(attrs={"class": "form-control", "placeholder": "Fatura Numarası"}),
            "tarih": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "dosya": forms.FileInput(attrs={"class": "form-control"}),
            "aciklama": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Varsa notunuz..."}),
        }
    
    def __init__(self, *args, **kwargs):
        kwargs.pop('satinalma', None)
        super().__init__(*args, **kwargs)

class SerbestFaturaGirisForm(forms.ModelForm):
    """
    SENARYO 2: Serbest Fatura (Manuel)
    """
    depo = forms.ModelChoiceField(
        queryset=Depo.objects.all(),
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Mallar hangi depoya girecek?"
    )

    class Meta:
        model = Fatura
        fields = ["tedarikci", "fatura_no", "tarih", "dosya", "aciklama"]
        widgets = {
            "tedarikci": forms.Select(attrs={"class": "form-select select2"}),
            "fatura_no": forms.TextInput(attrs={"class": "form-control"}),
            "tarih": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "dosya": forms.FileInput(attrs={"class": "form-control"}),
            "aciklama": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

class FaturaKalemForm(forms.ModelForm):
    class Meta:
        model = FaturaKalem
        fields = ["malzeme", "miktar", "fiyat", "kdv_oran", "aciklama"]
        widgets = {
            "malzeme": forms.Select(attrs={"class": "form-select"}),
            "miktar": forms.NumberInput(attrs={"class": "form-control", "step": "0.001", "min": "0"}),
            "fiyat": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001", "min": "0"}),
            "kdv_oran": forms.Select(attrs={"class": "form-select"}),
            "aciklama": forms.TextInput(attrs={"class": "form-control", "placeholder": "Açıklama"}),
        }

    def clean_miktar(self):
        v = to_decimal(self.cleaned_data.get("miktar", 0))
        if v <= 0:
            raise forms.ValidationError("Miktar 0'dan büyük olmalı.")
        return v

    def clean_fiyat(self):
        v = to_decimal(self.cleaned_data.get("fiyat", 0))
        if v < 0:
            raise forms.ValidationError("Fiyat negatif olamaz.")
        return v

FaturaKalemFormSet = inlineformset_factory(
    parent_model=Fatura,
    model=FaturaKalem,
    form=FaturaKalemForm,
    extra=5,
    can_delete=True
)

# ========================================================
# 3. HAKEDİŞ VE ÖDEME FORMLARI
# ========================================================
class HakedisForm(forms.ModelForm):
    class Meta:
        model = Hakedis
        fields = ['hakedis_no', 'tarih', 'donem_baslangic', 'donem_bitis', 'tamamlanma_orani', 'aciklama']
        widgets = {
            'hakedis_no': forms.NumberInput(attrs={'class': 'form-control'}),
            'tarih': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'donem_baslangic': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'donem_bitis': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'tamamlanma_orani': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'aciklama': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class OdemeForm(forms.ModelForm):
    tutar = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0,00'}),
        required=True
    )
    banka_adi = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    cek_no = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    vade_tarihi = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    aciklama = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    class Meta:
        model = Odeme
        fields = ['tedarikci', 'tarih', 'odeme_turu', 'tutar', 'para_birimi', 'banka_adi', 'cek_no', 'vade_tarihi', 'aciklama']
        widgets = {
            'tarih': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'tedarikci': forms.Select(attrs={'class': 'form-select'}),
            'odeme_turu': forms.Select(attrs={'class': 'form-select'}),
            'para_birimi': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_tutar(self):
        tutar = self.cleaned_data.get('tutar')
        # TÜRKÇE FORMAT DÜZELTME (Örn: 1.250,50 -> 1250.50)
        if isinstance(tutar, str):
            # 1. Binlik ayırıcı noktaları sil (1.250 -> 1250)
            tutar = tutar.replace('.', '')
            # 2. Ondalık virgülü noktaya çevir (1250,50 -> 1250.50)
            tutar = tutar.replace(',', '.')
            
        return to_decimal(tutar)