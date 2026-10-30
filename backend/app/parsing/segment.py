"""Split a multi-invoice PDF into invoice page ranges (rules only, no LLM).

Signals, strongest first:
1. "Page k of N": k == 1 starts an invoice, k > 1 continues the current one.
2. A new invoice-number value on the page (Invoice No / # / Bill # / Facture /
   Rechnung / Receipt No ...) that differs from the current invoice's number.
3. A header block (first lines) that differs from the previous page while the
   page looks like an invoice start ("Invoice"/"Receipt" title plus a total).
Otherwise the page continues the current invoice. Ranges are 1-based,
inclusive, ordered, and cover every page with no gaps or overlaps.
"""
from __future__ import annotations

import re

from app.contracts import ParsedPage

_PAGE_OF = re.compile(r"\b(?:page|seite|página|pagina)\s*(\d{1,4})\s*(?:of|/|von|de|sur)\s*(\d{1,4})\b", re.IGNORECASE)
_INV_NO = re.compile(
    r"(?:invoice|inv|bill|receipt|facture|rechnung|factura|fattura|order)\s*"
    r"(?:no\.?|number|num\.?|nr\.?|n[°º]|#|nummer|número|numéro)?\s*[:#]?\s*"
    r"([A-Z0-9][A-Z0-9\-/\.]{2,30}[A-Z0-9])",
    re.IGNORECASE,
)
_TITLE = re.compile(r"\b(invoice|receipt|facture|rechnung|factura|tax invoice)\b", re.IGNORECASE)
_TOTALISH = re.compile(r"\b(total|amount due|summe|montant|importe)\b", re.IGNORECASE)


def _invoice_number(text: str) -> str | None:
    for m in _INV_NO.finditer(text[:3000]):
        value = m.group(1).strip(".-/")
        if any(ch.isdigit() for ch in value):
            return value.upper()
    return None


def _header(text: str) -> tuple[str, ...]:
    lines = [ln.strip().lower() for ln in text.splitlines() if ln.strip()]
    return tuple(lines[:3])


def segment_pages(pages: list[ParsedPage]) -> list[tuple[int, int]]:
    if not pages:
        return []
    starts: list[int] = [pages[0].page_no]
    current_no = _invoice_number(pages[0].text)
    prev_header = _header(pages[0].text)
    for page in pages[1:]:
        text = page.text
        number = _invoice_number(text)
        header = _header(text)
        m = _PAGE_OF.search(text)
        if m:
            new = int(m.group(1)) == 1
        elif number and current_no and number != current_no:
            new = True
        elif number and not current_no:
            new = header != prev_header
        elif number:
            new = False
        else:
            new = bool(header and header != prev_header and _TITLE.search(text) and _TOTALISH.search(text))
        if new:
            starts.append(page.page_no)
            current_no = number
        elif number and not current_no:
            current_no = number
        prev_header = header
    last = pages[-1].page_no
    return [(s, (starts[i + 1] - 1) if i + 1 < len(starts) else last) for i, s in enumerate(starts)]
