"""Data models representing invoice documents, line items, and ground truth labels."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class LineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal

    def to_dict(self) -> Dict[str, str]:
        # Formats quantity as integer string if whole number, else decimal string
        qty_str = (
            f"{self.quantity:.0f}"
            if self.quantity == self.quantity.to_integral_value()
            else str(self.quantity)
        )
        return {
            "description": self.description,
            "quantity": qty_str,
            "unit_price": f"{self.unit_price:.2f}",
            "amount": f"{self.amount:.2f}",
        }


@dataclass
class InvoiceData:
    id: str
    filename: str
    invoice_number: str
    invoice_date: str  # ISO YYYY-MM-DD
    due_date: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_address: str = ""
    supplier_email: str = ""
    supplier_phone: str = ""
    supplier_tax_id: Optional[str] = None

    customer_name: Optional[str] = None
    customer_address: str = ""
    customer_tax_id: Optional[str] = None

    line_items: List[LineItem] = field(default_factory=list)
    subtotal: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    total: Decimal = Decimal("0.00")

    currency: Optional[str] = None  # ISO 4217 (USD, EUR, etc.) or None if ambiguous
    currency_symbol: str = "$"
    currency_position: str = "prefix"  # 'prefix' or 'suffix'
    locale: str = "en_US"
    layout: str = "modern_clean"
    split: str = "dev"  # 'dev' or 'test'
    quality: str = "digital"  # 'digital', 'good', 'fair', 'poor'
    expected_status: str = "COMPLETED"  # 'COMPLETED', 'NEEDS_REVIEW', 'FAILED'
    expected_error_code: str = ""
    notes: str = ""
    invoice_count: int = 1

    # Formatted display date for PDF rendering
    display_date: str = ""

    def to_label_dict(self) -> Dict[str, Any]:
        """Convert to CONTRACTS section 10 ground truth JSON object."""
        return {
            "invoice_number": {"value": self.invoice_number},
            "invoice_date": {"value": self.invoice_date},
            "supplier_name": {"value": self.supplier_name},
            "customer_name": {"value": self.customer_name},
            "subtotal": {
                "value": f"{self.subtotal:.2f}" if self.subtotal is not None else None
            },
            "tax": {
                "value": f"{self.tax:.2f}" if self.tax is not None else None
            },
            "total": {"value": f"{self.total:.2f}"},
            "currency": {"value": self.currency},
            "line_items": [item.to_dict() for item in self.line_items],
            "invoice_count": self.invoice_count,
        }

    def to_manifest_row(self) -> Dict[str, str]:
        """Convert to CONTRACTS section 10 manifest CSV row."""
        return {
            "id": self.id,
            "filename": self.filename,
            "kind": "pdf",
            "layout": self.layout,
            "supplier": self.supplier_name or "",
            "locale": self.locale,
            "currency": self.currency or "",
            "quality": self.quality,
            "split": self.split,
            "expected_status": self.expected_status,
            "expected_error_code": self.expected_error_code,
            "notes": self.notes,
        }
