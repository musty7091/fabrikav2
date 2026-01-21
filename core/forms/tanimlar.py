# core/forms/tanimlar.py
from django import forms
from core.models import Kategori, Depo, Tedarikci, Malzeme, IsKalemi

# ========================================================
# KATEGORİ VE TANIMLAMA FORMLARI
# ========================================================

class KategoriForm(forms.ModelForm):
    class Meta:
        model = Kategori
        fields = ['isim']
        widgets = {
            'isim': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Örn: Kaba İnşaat, İnce İşler...',
                'aria-label': 'Kategori Adı'
            }),
        }

class DepoForm(forms.ModelForm):
    class Meta:
        model = Depo
        fields = ['isim', 'adres', 'is_sanal', 'is_kullanim_yeri']
        widgets = {
            'isim': forms.TextInput(attrs={'class': 'form-control'}),
            'adres': forms.TextInput(attrs={'class': 'form-control'}),
            'is_sanal': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_kullanim_yeri': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class TedarikciForm(forms.ModelForm):
    class Meta:
        model = Tedarikci
        fields = ['firma_unvani', 'yetkili_kisi', 'telefon', 'adres']
        widgets = {
            'firma_unvani': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Örn: ABC İnşaat Ltd. Şti.', 'aria-label': 'Firma Unvanı'}),
            'yetkili_kisi': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ad Soyad', 'aria-label': 'Yetkili Kişi'}),
            'telefon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '05XX XXX XX XX', 'aria-label': 'Telefon'}),
            'adres': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'aria-label': 'Adres'}),
        }

class MalzemeForm(forms.ModelForm):
    class Meta:
        model = Malzeme
        fields = ['kategori', 'isim', 'marka', 'birim', 'kdv_orani', 'kritik_stok', 'aciklama']
        widgets = {
            'kategori': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Kategori'}),
            'isim': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Örn: Saten Alçı', 'aria-label': 'İsim'}),
            'marka': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Örn: Knauf', 'aria-label': 'Marka'}),
            'birim': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Birim'}),
            'kdv_orani': forms.Select(attrs={'class': 'form-select', 'aria-label': 'KDV Oranı'}),
            'kritik_stok': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '10', 'aria-label': 'Kritik Stok'}),
            'aciklama': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Açıklama...', 'aria-label': 'Açıklama'}),
        }

class IsKalemiForm(forms.ModelForm):
    class Meta:
        model = IsKalemi
        fields = ['kategori', 'isim', 'birim', 'hedef_miktar', 'kdv_orani', 'aciklama']
        widgets = {
            'kategori': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Kategori'}),
            'isim': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Örn: Temel Kazısı', 'aria-label': 'İsim'}),
            'birim': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Birim'}),
            'hedef_miktar': forms.NumberInput(attrs={'class': 'form-control', 'aria-label': 'Hedef Miktar'}),
            'kdv_orani': forms.Select(attrs={'class': 'form-select', 'aria-label': 'KDV Oranı'}),
            'aciklama': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Detay...', 'aria-label': 'Açıklama'}),
        }