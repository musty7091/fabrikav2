# core/services/__init__.py

# Eski yapı bozulmasın diye StockService'i buraya taşıyoruz
from .stock import StockService

# Yeni servisleri de buradan erişilebilir kılıyoruz (opsiyonel)
from .finans_invoices import InvoiceService
from .finans_payments import PaymentService