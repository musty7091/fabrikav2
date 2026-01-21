# core/forms/stok.py
from django import forms
from core.models import DepoTransfer, Depo, MalzemeTalep

# ========================================================
# STOK VE DEPO FORMLARI
# ========================================================

class DepoTransferForm(forms.ModelForm):
    class Meta:
        model = DepoTransfer
        fields = ['kaynak_depo', 'hedef_depo', 'malzeme', 'miktar', 'aciklama', 'tarih']
        widgets = {
            'kaynak_depo': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Kaynak Depo'}),
            'hedef_depo': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Hedef Depo'}),
            'malzeme': forms.Select(attrs={'class': 'form-select select2', 'aria-label': 'Malzeme'}),
            'miktar': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Transfer Miktarı', 'aria-label': 'Miktar'}),
            'aciklama': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Örn: Şantiyeye Sevk', 'aria-label': 'Açıklama'}),
            'tarih': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'aria-label': 'Tarih'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        try:
            sanal_depo = Depo.objects.filter(is_sanal=True).first()
            fiziksel_depo = Depo.objects.filter(is_sanal=False).first()

            if sanal_depo and not self.initial.get('kaynak_depo'):
                self.fields['kaynak_depo'].initial = sanal_depo
            if fiziksel_depo and not self.initial.get('hedef_depo'):
                self.fields['hedef_depo'].initial = fiziksel_depo
        except Exception:
            pass

    def clean(self):
        cleaned_data = super().clean()
        kaynak = cleaned_data.get('kaynak_depo')
        hedef = cleaned_data.get('hedef_depo')
        malzeme = cleaned_data.get('malzeme')
        miktar = cleaned_data.get('miktar')

        if not (kaynak and hedef and malzeme and miktar):
            return cleaned_data

        if kaynak == hedef:
            raise forms.ValidationError("Kaynak ve Hedef depo aynı olamaz.")

        # Eksi stok kontrolü
        try:
            mevcut_stok = malzeme.depo_stogu(kaynak.id)
            if mevcut_stok < miktar:
                raise forms.ValidationError(
                    f"Hata: Kaynak depoda ({kaynak.isim}) yeterli stok yok! Mevcut: {mevcut_stok}"
                )
        except AttributeError:
            pass

        return cleaned_data

class TalepForm(forms.ModelForm):
    class Meta:
        model = MalzemeTalep
        fields = ['malzeme', 'is_kalemi', 'miktar', 'oncelik', 'proje_yeri', 'aciklama']
        widgets = {
            'malzeme': forms.Select(attrs={'class': 'form-select select2', 'aria-label': 'Malzeme'}),
            'is_kalemi': forms.Select(attrs={'class': 'form-select select2', 'aria-label': 'İş Kalemi'}),
            'miktar': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Örn: 100', 'aria-label': 'Miktar'}),
            'oncelik': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Öncelik'}),
            'proje_yeri': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Örn: A Blok - 1. Kat', 'aria-label': 'Proje Yeri'}),
            'aciklama': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'aria-label': 'Açıklama'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        malzeme = cleaned_data.get('malzeme')
        is_kalemi = cleaned_data.get('is_kalemi')

        if not malzeme and not is_kalemi:
            raise forms.ValidationError("Lütfen Malzeme veya İş Kalemi alanlarından birini seçiniz.")
        if malzeme and is_kalemi:
            raise forms.ValidationError("İkisini aynı anda seçemezsiniz.")
        return cleaned_data