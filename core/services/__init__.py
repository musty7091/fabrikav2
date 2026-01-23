# core/services/__init__.py
"""
SERVICES PACKAGE

KURAL:
Bu dosyada hiçbir servisi doğrudan import etmeyin.
Aksi halde core.models ile circular import oluşur.
"""

from typing import Any

__all__ = [
    "StockService",
    "PaymentService",
    "InvoiceService",
]

def __getattr__(name: str) -> Any:
    if name == "StockService":
        from .stock import StockService
        return StockService
    if name == "PaymentService":
        from .finans_payments import PaymentService
        return PaymentService
    if name == "InvoiceService":
        from .finans_invoices import InvoiceService
        return InvoiceService
    raise AttributeError(f"module 'core.services' has no attribute '{name}'")
