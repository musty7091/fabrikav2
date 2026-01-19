from django import forms
from decimal import Decimal
from .models import (
    DepoTransfer, Depo, Teklif, Malzeme, 
    IsKalemi, Tedarikci, MalzemeTalep, KDV_ORANLARI, Fatura, Hakedis, Odeme, Kategori
)

# ========================================================
# 0. KATEGORİ (İMALAT TÜRÜ) FORMU
# ========================================================

class KategoriForm(forms.ModelForm):
    class Meta:
        model = Kategori
        fields = ['isim']
        widgets = {
            'isim': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Örn: Kaba İnşaat, İnce İşler...', 'aria-label': 'Kategori Adı'}),
        }

# ========================================================
# 1. DEPO TRANSFER FORMU
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
        super(DepoTransferForm, self).__init__(*args, **kwargs)
        
        try:
            sanal_depo = Depo.objects.filter(is_sanal=True).first()
            fiziksel_depo = Depo.objects.filter(is_sanal=False).first()
            
            if sanal_depo and not self.initial.get('kaynak_depo'):
                self.fields['kaynak_depo'].initial = sanal_depo
            if fiziksel_depo and not self.initial.get('hedef_depo'):
                self.fields['hedef_depo'].initial = fiziksel_depo
        except:
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

        # Eksi Stok Kontrolü
        try:
            mevcut_stok = malzeme.depo_stogu(kaynak.id)
            if mevcut_stok < miktar:
                raise forms.ValidationError(
                    f"Hata: Kaynak depoda ({kaynak.isim}) yeterli stok yok! Mevcut: {mevcut_stok}"
                )
        except AttributeError:
            pass
            
        return cleaned_data

# ========================================================
# 2. TEKLİF GİRİŞ FORMU
# ========================================================

class TeklifForm(forms.ModelForm):
    kdv_orani_secimi = forms.ChoiceField(
        choices=[('', 'Seçiniz...')] + list(KDV_ORANLARI), 
        label="KDV Oranı", 
        required=True,
        widget=forms.Select(attrs={'class': 'form-select', 'aria-label': 'KDV Oranı'})
    )

    class Meta:
        model = Teklif
        fields = [
            'talep', # Bu alan initial veriyi yakalamak için listeye eklendi
            'tedarikci', 
            'malzeme', 'is_kalemi',
            'miktar', 'birim_fiyat', 'para_birimi', 
            'kdv_dahil_mi', 'teklif_dosyasi'
        ]
        widgets = {
            'talep': forms.HiddenInput(), # Ekranda görünmesin ama veriyi taşısın
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

# ========================================================
# 3. TANIMLAMA FORMLARI
# ========================================================

class DepoForm(forms.ModelForm):
    class Meta:
        model = Depo
        fields = ['isim', 'adres', 'is_sanal', 'is_kullanim_yeri'] # Buraya eklendi
        widgets = {
            'isim': forms.TextInput(attrs={'class': 'form-control'}),
            'adres': forms.TextInput(attrs={'class': 'form-control'}),
            'is_sanal': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_kullanim_yeri': forms.CheckboxInput(attrs={'class': 'form-check-input'}), # Buraya eklendi
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

# ========================================================
# 4. TALEP FORMLARI
# ========================================================

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

class FaturaGirisForm(forms.ModelForm):
    class Meta:
        model = Fatura
        fields = ['fatura_no', 'tarih', 'depo', 'miktar', 'tutar', 'dosya']
        widgets = {
            'fatura_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Fatura No', 'aria-label': 'Fatura No'}),
            'tarih': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'aria-label': 'Fatura Tarihi'}),
            'depo': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Depo'}),
            'miktar': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'aria-label': 'Miktar'}),
            'tutar': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'aria-label': 'Tutar'}),
            'dosya': forms.FileInput(attrs={'class': 'form-control', 'aria-label': 'Dosya'}),
        }
    
    def __init__(self, *args, **kwargs):
        super(FaturaGirisForm, self).__init__(*args, **kwargs)
        self.fields['depo'].required = True
        self.fields['depo'].empty_label = "Depo Seçiniz (Zorunlu)"

class HakedisForm(forms.ModelForm):
    class Meta:
        model = Hakedis
        fields = ['hakedis_no', 'tarih', 'donem_baslangic', 'donem_bitis', 'tamamlanma_orani', 'aciklama']
        widgets = {
            'hakedis_no': forms.NumberInput(attrs={'class': 'form-control', 'value': 1, 'aria-label': 'Hakediş No'}),
            'tarih': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'aria-label': 'Hakediş Tarihi'}),
            'donem_baslangic': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'aria-label': 'Dönem Başlangıç'}),
            'donem_bitis': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'aria-label': 'Dönem Bitiş'}),
            'tamamlanma_orani': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Örn: 20', 'step': '0.01', 'aria-label': 'Tamamlanma Oranı'}),
            'aciklama': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'aria-label': 'Açıklama'}),
        }

class OdemeForm(forms.ModelForm):
    # ÇÖZÜM: Tutar alanını CharField olarak tanımlıyoruz ki virgül kabul etsin.
    tutar = forms.CharField(
        label="Tutar",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0,00', 'aria-label': 'Tutar'}),
        required=True
    )
    
    # Zorunlu olmayan alanlar
    banka_adi = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Banka adı...', 'aria-label': 'Banka Adı'}))
    cek_no = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Çek No...', 'aria-label': 'Çek No'}))
    vade_tarihi = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'aria-label': 'Vade Tarihi'}))
    aciklama = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Açıklama...', 'aria-label': 'Açıklama'}))

    class Meta:
        model = Odeme
        fields = ['tedarikci', 'tarih', 'odeme_turu', 'tutar', 'para_birimi', 'banka_adi', 'cek_no', 'vade_tarihi', 'aciklama']
        widgets = {
            'tarih': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'aria-label': 'İşlem Tarihi'}),
            'tedarikci': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Tedarikçi'}),
            'odeme_turu': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Ödeme Türü'}),
            'para_birimi': forms.Select(attrs={'class': 'form-select', 'aria-label': 'Para Birimi'}),
        }

    # "Sayı Girin" hatasını çözen kısım:
    def clean_tutar(self):
        tutar = self.cleaned_data.get('tutar')
        if tutar:
            # Gelen string değerdeki virgülü noktaya çeviriyoruz
            if isinstance(tutar, str):
                tutar = tutar.replace(',', '.')
            
            try:
                # Sayıya çevirmeyi deniyoruz
                return Decimal(tutar)
            except:
                raise forms.ValidationError("Lütfen geçerli bir sayı giriniz.")
        return Decimal('0')