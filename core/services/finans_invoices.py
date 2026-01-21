# core/services/finans_invoices.py
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.models import Depo, DepoHareket, FaturaKalem

class InvoiceService:
    
    @staticmethod
    @transaction.atomic
    def fatura_olustur_siparisten(fatura, siparis):
        """
        SENARYO 1 İÇİN:
        Sipariş (SatinAlma) verilerini kullanarak faturayı ve kalemini OTOMATİK oluşturur.
        Kullanıcıdan kalem bilgisi beklemez.
        """
        # 1. Fatura Başlığını Tamamla ve Kaydet
        fatura.satinalma = siparis
        fatura.tedarikci = siparis.teklif.tedarikci
        fatura.save()

        # 2. Sipariş verilerini çek (Teklif'ten)
        teklif = siparis.teklif
        
        # Miktar: Faturaya konu olan miktar.
        islem_miktari = siparis.toplam_miktar 
        
        malzeme = teklif.malzeme
        
        # Fiyatlar
        birim_fiyat = teklif.birim_fiyat
        kdv_orani = teklif.kdv_orani
        
        # 3. Fatura Kalemini Otomatik Oluştur
        # Not: Malzeme varsa oluştur, hizmet ise (malzeme=None) sisteminize göre ayarlanmalı.
        # FaturaKalem modelinde malzeme alanı zorunlu olduğu için sadece malzeme varsa devam ediyoruz.
        if malzeme:
            kalem = FaturaKalem.objects.create(
                fatura=fatura,
                malzeme=malzeme,
                miktar=islem_miktari,
                fiyat=birim_fiyat,
                kdv_oran=kdv_orani,
                aciklama=f"Siparişten otomatik: {siparis.id}"
            )
            
            # 4. Stok Hareketi (Sanal Depo Girişi)
            sanal_depo = Depo.objects.filter(is_sanal=True).first()
            if sanal_depo:
                DepoHareket.objects.create(
                    ref_type="FATURA_KALEM",
                    ref_id=kalem.id,
                    ref_direction="IN",
                    malzeme=malzeme,
                    depo=sanal_depo,
                    tarih=fatura.tarih or timezone.now().date(),
                    islem_turu="giris",
                    miktar=islem_miktari,
                    tedarikci=fatura.tedarikci,
                    aciklama=f"Fatura #{fatura.fatura_no} (Oto. Sipariş Girişi)"
                )
            
            # Siparişi Güncelle (Faturalanan Miktar)
            siparis.faturalanan_miktar = Decimal(siparis.faturalanan_miktar) + Decimal(islem_miktari)
            siparis.save()
            
        return fatura

    @staticmethod
    @transaction.atomic
    def fatura_kaydet_manuel(fatura, kalemler_formset, depo_id=None):
        """
        SENARYO 2 İÇİN:
        Serbest fatura. Kalemler formset'ten gelir.
        Stoklar seçilen depoya girer.
        """
        fatura.save()
        kalemler = kalemler_formset.save(commit=False)
        
        # Seçilen depo (Formdan gelen)
        hedef_depo = None
        if depo_id:
            hedef_depo = Depo.objects.filter(id=depo_id).first()
        
        # Eğer depo seçilmediyse Sanal Depo varsayılan olsun
        if not hedef_depo:
            hedef_depo = Depo.objects.filter(is_sanal=True).first()

        gercek_kalem_sayisi = 0
        for k in kalemler:
            # Geçersiz satırları atla
            if not k.malzeme_id or not k.miktar or k.miktar <= 0:
                continue

            k.fatura = fatura
            k.save()
            gercek_kalem_sayisi += 1

            # Stok Hareketi
            if hedef_depo:
                DepoHareket.objects.create(
                    ref_type="FATURA_KALEM",
                    ref_id=k.id,
                    ref_direction="IN",
                    malzeme=k.malzeme,
                    depo=hedef_depo,
                    tarih=fatura.tarih or timezone.now().date(),
                    islem_turu="giris",
                    miktar=k.miktar,
                    tedarikci=fatura.tedarikci,
                    aciklama=f"Serbest Fatura #{fatura.fatura_no}"
                )

        # Silinenleri temizle
        for obj in kalemler_formset.deleted_objects:
            obj.delete()

        if gercek_kalem_sayisi == 0:
            raise ValidationError("En az 1 geçerli satır girmelisiniz.")

        return fatura