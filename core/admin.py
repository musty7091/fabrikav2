from django.contrib import admin
from django.shortcuts import redirect
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
import json

from .models import (
    Kategori, IsKalemi, Tedarikci, Teklif, SatinAlma, GiderKategorisi, Harcama, Odeme, 
    Malzeme, DepoHareket, Hakedis, MalzemeTalep, Depo, DepoTransfer
)
from .utils import tcmb_kur_getir 
from .forms import DepoTransferForm 

# --- YARDIMCI MODELLER ---
class IsKalemiInline(admin.TabularInline):
    model = IsKalemi
    extra = 1

@admin.register(Kategori)
class KategoriAdmin(admin.ModelAdmin):
    inlines = [IsKalemiInline]
    list_display = ('isim',)

@admin.register(IsKalemi)
class IsKalemiAdmin(admin.ModelAdmin):
    list_display = ('isim', 'kategori', 'hedef_miktar', 'birim', 'kdv_orani')
    list_filter = ('kategori',)
    search_fields = ('isim',)

@admin.register(Tedarikci)
class TedarikciAdmin(admin.ModelAdmin):
    list_display = ('firma_unvani', 'yetkili_kisi', 'telefon')
    search_fields = ('firma_unvani',)

# --- DEPO VE MALZEME YÖNETİMİ ---

@admin.register(Depo)
class DepoAdmin(admin.ModelAdmin):
    list_display = ('isim', 'adres', 'is_sanal_goster')
    search_fields = ('isim',) 
    
    def is_sanal_goster(self, obj):
        return "🌐 Sanal (Tedarikçi)" if obj.is_sanal else "🏭 Fiziksel Depo"
    is_sanal_goster.short_description = "Depo Türü"

@admin.register(Malzeme)
class MalzemeAdmin(admin.ModelAdmin):
    list_display = ('isim', 'kategori', 'marka', 'birim', 'stok_durumu', 'kritik_stok')
    list_filter = ('kategori',)
    search_fields = ('isim', 'marka')
    
    # DepoHareket'te autocomplete kullanmak için bu gerekli
    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        return queryset, use_distinct

    def stok_durumu(self, obj):
        stok = obj.stok
        renk = "green"
        if stok <= obj.kritik_stok:
            renk = "red"
        elif stok <= obj.kritik_stok * 1.2:
            renk = "orange"
        
        return mark_safe(f'<span style="color:{renk}; font-weight:bold;">{stok}</span>')
    stok_durumu.short_description = "Anlık Stok"

@admin.register(DepoTransfer)
class DepoTransferAdmin(admin.ModelAdmin):
    form = DepoTransferForm
    list_display = ('tarih', 'malzeme', 'miktar', 'kaynak_depo', 'hedef_depo')
    list_filter = ('kaynak_depo', 'hedef_depo')
    autocomplete_fields = ['malzeme']

@admin.register(DepoHareket)
class DepoHareketAdmin(admin.ModelAdmin):
    list_display = ('tarih', 'islem_turu', 'depo', 'malzeme', 'miktar', 'tedarikci')
    list_filter = ('islem_turu', 'depo')
    search_fields = ('malzeme__isim', 'irsaliye_no', 'tedarikci__firma_unvani')
    autocomplete_fields = ['malzeme', 'tedarikci', 'depo']

# --- TALEP YÖNETİMİ ---

@admin.register(MalzemeTalep)
class MalzemeTalepAdmin(admin.ModelAdmin):
    list_display = ('talep_ozeti', 'miktar_goster', 'talep_eden', 'oncelik_durumu', 'durum_goster', 'tarih')
    list_filter = ('durum', 'oncelik')
    # Arama yaparken hem malzeme hem iş kalemine bak
    search_fields = ('malzeme__isim', 'is_kalemi__isim', 'aciklama')
    
    def talep_ozeti(self, obj):
        if obj.malzeme: return f"📦 {obj.malzeme.isim}"
        if obj.is_kalemi: return f"🏗️ {obj.is_kalemi.isim}"
        return "-"
    talep_ozeti.short_description = "Talep Edilen"

    def miktar_goster(self, obj):
        birim = obj.malzeme.get_birim_display() if obj.malzeme else obj.is_kalemi.get_birim_display()
        return f"{obj.miktar} {birim}"
    miktar_goster.short_description = "Miktar"

    def oncelik_durumu(self, obj):
        renk = "black"
        if obj.oncelik == 'acil': renk = "orange"
        if obj.oncelik == 'cok_acil': renk = "red"
        return mark_safe(f'<span style="color:{renk}; font-weight:bold;">{obj.get_oncelik_display()}</span>')
    oncelik_durumu.short_description = "Aciliyet"

    def durum_goster(self, obj):
        ikon = "⏳"
        if obj.durum == 'onaylandi': ikon = "✅"
        if obj.durum == 'tamamlandi': ikon = "📦"
        if obj.durum == 'red': ikon = "❌"
        return f"{ikon} {obj.get_durum_display()}"
    durum_goster.short_description = "Durum"

# --- TEKLİF VE SATINALMA ---

@admin.register(Teklif)
class TeklifAdmin(admin.ModelAdmin):
    list_display = ('urun_adi', 'tedarikci', 'toplam_fiyat_goster', 'durum')
    list_filter = ('durum', 'tedarikci')
    search_fields = ('malzeme__isim', 'is_kalemi__isim', 'tedarikci__firma_unvani')
    
    def urun_adi(self, obj):
        return str(obj)
    urun_adi.short_description = "Teklif İçeriği"

    def toplam_fiyat_goster(self, obj):
        return f"{obj.toplam_fiyat_tl:,.2f} TL"
    toplam_fiyat_goster.short_description = "Toplam Tutar (KDV Dahil)"

@admin.register(SatinAlma)
class SatinAlmaAdmin(admin.ModelAdmin):
    # YENİ MODEL YAPISINA GÖRE GÜNCELLENDİ
    list_display = ('teklif', 'siparis_tarihi', 'teslimat_durumu', 'ilerleme_durumu')
    list_filter = ('teslimat_durumu', 'siparis_tarihi')
    search_fields = ('teklif__tedarikci__firma_unvani', 'teklif__malzeme__isim')
    
    def ilerleme_durumu(self, obj):
        yuzde = obj.tamamlanma_yuzdesi
        renk = "success" if yuzde == 100 else ("warning" if yuzde > 0 else "danger")
        html = f'''
            <div style="width:100px; background:#e9ecef; border-radius:3px; height:15px;">
                <div style="width:{yuzde}%; background-color:var(--bs-{renk}); height:100%; border-radius:3px;"></div>
            </div>
            <small>%{yuzde:.0f} Geldi</small>
        '''
        return mark_safe(html)
    ilerleme_durumu.short_description = "Teslimat Durumu"

# --- FİNANS ---

@admin.register(Odeme)
class OdemeAdmin(admin.ModelAdmin):
    list_display = ('tedarikci', 'tutar', 'odeme_turu', 'tarih')
    list_filter = ('odeme_turu',)
    search_fields = ('tedarikci__firma_unvani',)

@admin.register(Harcama)
class HarcamaAdmin(admin.ModelAdmin):
    list_display = ('aciklama', 'tutar', 'kategori', 'tarih')
    list_filter = ('kategori',)

@admin.register(GiderKategorisi)
class GiderKategorisiAdmin(admin.ModelAdmin):
    pass

@admin.register(Hakedis)
class HakedisAdmin(admin.ModelAdmin):
    list_display = ('satinalma', 'hakedis_no', 'tarih', 'onay_durumu')