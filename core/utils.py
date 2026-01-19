import requests
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP

def tcmb_kur_getir():
    """
    TCMB'den güncel USD, EUR ve GBP kurlarını çeker.
    Hata durumunda varsayılan olarak 1.0 döner.
    """
    url = "https://www.tcmb.gov.tr/kurlar/today.xml"
    
    kurlar = {
        'USD': Decimal('1.0'),
        'EUR': Decimal('1.0'),
        'GBP': Decimal('1.0') # Sterlin Eklendi
    }
    
    try:
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            
            for currency in root.findall('Currency'):
                kod = currency.get('Kod')
                
                # Banknot Satış yoksa Forex Satış (Piyasa)
                satis = currency.find('BanknoteSelling').text
                if not satis:
                    satis = currency.find('ForexSelling').text
                    
                if satis and kod in ['USD', 'EUR', 'GBP']:
                    # Nokta/Virgül karmaşasını önlemek için güvenli dönüşüm
                    deger = Decimal(satis)
                    kurlar[kod] = deger

    except Exception as e:
        print(f"Kur çekme hatası: {e}")
        
    return kurlar

def to_decimal(value, precision=2):
    if value is None or value == '':
        return Decimal('0.00')
    
    if isinstance(value, (Decimal, float, int)):
        return Decimal(str(value)).quantize(
            Decimal('1.' + '0' * precision), 
            rounding=ROUND_HALF_UP
        )
    
    try:
        # Sadece string gelirse temizlik yap
        clean_value = str(value).replace('.', '').replace(',', '.')
        return Decimal(clean_value).quantize(
            Decimal('1.' + '0' * precision), 
            rounding=ROUND_HALF_UP
        )
    except:
        return Decimal('0.00')