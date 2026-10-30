"""Invoice layout renderers registry."""

from typing import Callable
from tools.datagen.models import InvoiceData
from tools.datagen.layouts.modern_clean import render_modern_clean
from tools.datagen.layouts.classic_corporate import render_classic_corporate
from tools.datagen.layouts.compact_slip import render_compact_slip
from tools.datagen.layouts.bold_banner import render_bold_banner
from tools.datagen.layouts.minimalist_sidebar import render_minimalist_sidebar
from tools.datagen.layouts.international_multilingual import render_international_multilingual
from tools.datagen.layouts.receipts import render_receipt_retail, render_receipt_thermal

LAYOUT_RENDERERS: dict[str, Callable[[InvoiceData, str], None]] = {
    "modern_clean": render_modern_clean,
    "classic_corporate": render_classic_corporate,
    "compact_slip": render_compact_slip,
    "bold_banner": render_bold_banner,
    "minimalist_sidebar": render_minimalist_sidebar,
    "international_multilingual": render_international_multilingual,
    "receipt_thermal": render_receipt_thermal,
    "receipt_retail": render_receipt_retail,
}


def render_invoice_pdf(invoice: InvoiceData, output_path: str) -> None:
    """Render an invoice to PDF using its specified layout."""
    if invoice.layout not in LAYOUT_RENDERERS:
        raise ValueError(f"Unknown layout: {invoice.layout}")
    LAYOUT_RENDERERS[invoice.layout](invoice, output_path)
