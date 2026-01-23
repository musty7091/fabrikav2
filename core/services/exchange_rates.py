from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime
import urllib.request
import xml.etree.ElementTree as ET


@dataclass
class RateResult:
    ok: bool
    rate: Decimal | None = None
    source: str | None = None
    message: str | None = None


# ✅ tcmb1 hostname mismatch yaşattığı için www kullanıyoruz
TCMB_TODAY_XML = "https://www.tcmb.gov.tr/kurlar/today.xml"
TCMB_DATE_XML_FMT = "https://www.tcmb.gov.tr/kurlar/{yyyymm}/{ddmmyyyy}.xml"


def _d(s: str) -> Decimal:
    s = (s or "").strip().replace(",", ".")
    return Decimal(s)


def _fetch_xml(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read()


def _parse_try_per_currency_from_xml(xml_data: bytes, currency: str) -> RateResult:
    currency = (currency or "").upper().strip()
    if not currency:
        return RateResult(ok=False, message="Para birimi boş")

    if currency == "TRY":
        return RateResult(ok=True, rate=Decimal("1.0000"), source="local")

    root = ET.fromstring(xml_data)

    for cur in root.findall("Currency"):
        code = (cur.attrib.get("CurrencyCode") or "").upper().strip()
        if code != currency:
            continue

        # Öncelik: ForexSelling, boşsa BanknoteSelling
        fs = (cur.findtext("ForexSelling") or "").strip()
        bs = (cur.findtext("BanknoteSelling") or "").strip()
        val = fs or bs

        if not val:
            return RateResult(ok=False, message=f"TCMB içinde kur boş: {currency}")

        rate = _d(val).quantize(Decimal("0.0001"))
        return RateResult(ok=True, rate=rate, source="TCMB")

    return RateResult(ok=False, message=f"TCMB içinde bulunamadı: {currency}")


def _as_date(d: str | date | None) -> date | None:
    if d is None:
        return None
    if isinstance(d, date):
        return d
    d = (d or "").strip()
    if not d:
        return None
    # Beklenen: YYYY-MM-DD
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


def get_try_per_currency(currency: str, for_date: str | date | None = None) -> RateResult:
    """
    1 CURRENCY = ? TRY
    - for_date None ise today.xml
    - for_date varsa o tarihin TCMB XML'i
    """
    currency = (currency or "").upper().strip()
    if currency == "TRY":
        return RateResult(ok=True, rate=Decimal("1.0000"), source="local")

    dt = _as_date(for_date)

    try:
        if dt is None:
            xml_data = _fetch_xml(TCMB_TODAY_XML)
            res = _parse_try_per_currency_from_xml(xml_data, currency)
            if res.ok:
                res.source = "TCMB today.xml"
            return res

        yyyymm = dt.strftime("%Y%m")
        ddmmyyyy = dt.strftime("%d%m%Y")
        url = TCMB_DATE_XML_FMT.format(yyyymm=yyyymm, ddmmyyyy=ddmmyyyy)
        xml_data = _fetch_xml(url)
        res = _parse_try_per_currency_from_xml(xml_data, currency)
        if res.ok:
            res.source = f"TCMB {dt.isoformat()}"
        return res

    except Exception as e:
        return RateResult(ok=False, message=str(e))
