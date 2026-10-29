"""Rules-based field extractor for invoices.

Extracts: invoice_number, invoice_date, supplier_name, customer_name,
subtotal, tax, total, currency, line_items.

Every field is returned as a dict with:
  value, confidence, evidence, page
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.contracts import (
    ExtractedField,
    ExtractedLineItem,
    ExtractionMethod,
    ExtractionResult,
    ParsedPage,
)
from app.extraction.normalize import (
    CurrencyResult,
    DateResult,
    detect_currency,
    parse_date,
    parse_decimal,
)

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def _norm_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _round_conf(c: float) -> float:
    return round(c, 2)


def _field(value: Any, confidence: float, evidence: str | None, page: int | None) -> ExtractedField:
    """Build an ExtractedField, coercing to None if confidence is 0."""
    if value is None:
        return ExtractedField(value=None, confidence=0.0, evidence=None, page=None)
    return ExtractedField(value=value, confidence=_round_conf(confidence), evidence=evidence, page=page)


def _empty_field() -> ExtractedField:
    return ExtractedField(value=None, confidence=0.0, evidence=None, page=None)


# ---------------------------------------------------------------------------
# Invoice-number patterns (multi-language)
# ---------------------------------------------------------------------------

# Common words that should never be returned as an invoice number.
_INV_NUM_REJECTS = re.compile(
    r"^(?:data|date|number|no|num|ref|invoice|receipt|bill|order|"
    r"from|to|page|amount|total|tax|vat|currency|subtotal|net)s?$",
    re.IGNORECASE,
)

# Labels that MUST include a qualifier (no, num, #, nr …) or be an
# unambiguous word like "Rechnungsnummer". "invoice" alone is NOT a label
# because it appears in headings; it must be followed by no/num/number/#/nr.
_INV_NUM_LABELS = re.compile(
    r"(?:"
    r"invoice\s*(?:no|num(?:ber)?|#|nr)\b|"
    r"inv\.?\s*(?:no|num(?:ber)?|#|nr)\b|"
    r"facture\s*(?:no|n[°o]|num(?:éro)?)\b|"
    r"num[ée]ro\s*(?:de\s*)?facture\b|"
    r"n[°o]\s*(?:de\s*)?facture\b|"
    r"rechnungsnummer\b|"
    r"rechnung\s*(?:nr|nummer)\b|"
    r"factura\s*(?:no|n[°o]|n[úu]m(?:ero)?)\b|"
    r"n[úu]mero\s*(?:de\s*)?factura\b|"
    r"bill\s*(?:no|num(?:ber)?|#|nr)\b|"
    r"receipt\s*(?:no|num(?:ber)?|#|nr)\b|"
    r"order\s*(?:no|num(?:ber)?|#|nr)\b|"
    r"ref(?:erence)?\s*(?:no|num(?:ber)?|#|nr)\b"
    r")[:\s#-]*([A-Z0-9][A-Z0-9\-/_. ]{0,29})",
    re.IGNORECASE,
)


def _extract_invoice_number(pages: list[ParsedPage]) -> ExtractedField:
    for page in pages:
        text = page.text
        for m in _INV_NUM_LABELS.finditer(text):
            raw = m.group(1).strip().rstrip(".,;: ")
            # Must contain at least one digit and not be a common word
            if not re.search(r"\d", raw):
                continue
            if _INV_NUM_REJECTS.match(raw):
                continue
            evidence = _norm_ws(m.group(0))
            return _field(raw, 0.85, evidence, page.page_no)
    return _empty_field()


# ---------------------------------------------------------------------------
# Date patterns
# ---------------------------------------------------------------------------

_DATE_LABELS = re.compile(
    r"\b(?:"
    r"invoice\s*date|date\s*of\s*invoice|"
    r"rechnungsdatum|date\s*de\s*facture|date\s*d['\u2019]?(?:emission|facture)|"
    r"bill(?:ing)?\s*date|receipt\s*date|issued?\s*(?:on|date)?|"
    # Simple labels last so the multi-word ones above take priority
    r"datum|fecha|date"
    r")\b[:\s]*"
    r"("
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|"       # ISO: 2026-03-14
    r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"      # dd/mm/yy or mm/dd/yyyy
    r"\d{1,2}(?:\.|\s)+\w+[\s.,]+\d{2,4}|"   # 14. März 2026, 14 March 2026, 14.März 2026
    r"\w+\s+\d{1,2}[,\s]+\d{4}"              # March 14, 2026
    r")",
    re.IGNORECASE,
)

_DATE_STANDALONE = re.compile(
    r"\b("
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|"
    r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"\d{1,2}(?:\.|\s)+\w{3,10}[\s.,]+\d{4}|"   # 14. März 2026 or 14 March 2026
    r"\w{3,10}\s+\d{1,2}[,\s]+\d{4}"
    r")\b",
    re.IGNORECASE,
)


def _extract_invoice_date(pages: list[ParsedPage]) -> ExtractedField:
    # Search all pages for a labelled date
    for page in pages:
        text = page.text
        for m in _DATE_LABELS.finditer(text):
            raw_date = m.group(1).strip()
            dr: DateResult = parse_date(raw_date, text)
            if dr.iso_date:
                evidence = _norm_ws(m.group(0))
                conf = 0.75 if dr.is_ambiguous else 0.90
                return _field(dr.iso_date, conf, evidence, page.page_no)

    # Fallback: any date-like token in first page
    for page in pages[:2]:
        text = page.text
        for m in _DATE_STANDALONE.finditer(text):
            raw_date = m.group(1).strip()
            dr = parse_date(raw_date, text)
            if dr.iso_date:
                evidence = _norm_ws(m.group(0))
                conf = 0.50 if dr.is_ambiguous else 0.65
                return _field(dr.iso_date, conf, evidence, page.page_no)

    return _empty_field()


# ---------------------------------------------------------------------------
# Money labels (subtotal, tax, total)
# ---------------------------------------------------------------------------

_MONEY_RE = re.compile(
    r"[-$€£¥₹৳]?\s*[\d,. ']+(?:\.\d+)?",
)


def _extract_money_labeled(
    pattern: re.Pattern[str],
    text: str,
    page_no: int,
    base_conf: float = 0.82,
) -> ExtractedField:
    m = pattern.search(text)
    if not m:
        return _empty_field()
    # Try to grab the trailing number after the label
    after = text[m.end():]
    nm = re.match(r"\s*:?\s*([-(\$€£¥₹৳]?\s*[\d,. ']+(?:\.\d{1,4})?)", after)
    if not nm:
        return _empty_field()
    raw_num = nm.group(1).strip()
    parsed = parse_decimal(raw_num)
    if parsed is None:
        return _empty_field()
    evidence = _norm_ws(m.group(0) + " " + nm.group(0))
    return _field(parsed, base_conf, evidence, page_no)


_SUBTOTAL_PAT = re.compile(
    r"\b(?:subtotal|sub[-\s]?total|net\s*amount|net\s*total|montant\s*ht|"
    r"nettobetrag|netto|importe\s*neto)\b",
    re.IGNORECASE,
)

_TAX_PAT = re.compile(
    r"\b(?:tax(?:es)?|vat|gst|tva|mwst|ust|hst|sales\s*tax|"
    r"taxe[s]?\s*(?:sur\s*la\s*valeur\s*ajoutée)?|steuer)\b",
    re.IGNORECASE,
)

_TOTAL_PAT = re.compile(
    r"\b(?:total\s*(?:amount\s*due|amount|ttc|a\s*payer|due|dû|inkl\.?\s*mwst)?|"
    r"amount\s*due|grand\s*total|balance\s*due|"
    r"montant\s*(?:total|ttc|dû)|gesamtbetrag|betrag|"
    r"importe\s*total|total\s*a\s*pagar)\b",
    re.IGNORECASE,
)


def _best_money_match(
    pattern: re.Pattern[str],
    pages: list[ParsedPage],
    base_conf: float = 0.82,
) -> ExtractedField:
    """Search pages, return first labelled match."""
    for page in pages:
        result = _extract_money_labeled(pattern, page.text, page.page_no, base_conf)
        if result.value is not None:
            return result
    return _empty_field()


# ---------------------------------------------------------------------------
# Supplier (top-of-page + "From"/"Seller" labels)
# ---------------------------------------------------------------------------

_SUPPLIER_LABELS = re.compile(
    r"(?:from|seller|vendor|supplied\s*by|bill(?:ed)?\s*from|"
    r"de\s*(?:la\s*part\s*de)?|expedidor|absender|verkäufer)\s*[:\s]*"
    r"([A-Z][^\n]{2,60})",
    re.IGNORECASE,
)

_COMPANY_SUFFIXES = re.compile(
    r"\b(?:Inc\.?|LLC\.?|Ltd\.?|Corp\.?|Co\.?|GmbH|AG|SAS|SARL|SL|S\.?A\.?|"
    r"PLC|LLP|OHG|KG|BV|NV)\b",
    re.IGNORECASE,
)

# Lines that must be skipped when heuristically picking the supplier name.
_LINE_IS_LABEL = re.compile(
    r"(?:"
    r"invoice|receipt|bill|tax\s*invoice|facture|rechnung|factura|"
    r"(?:invoice|receipt|bill|ref|order|rechnungs?)\s*(?:no|num(?:ber)?|#|nr)|"
    r"rechnungsnummer|"
    r"datum|date|fecha|issued|from\b|sold\s*to|bill(?:ed)?\s*to|ship(?:ped)?\s*to|"
    r"subtotal|total|tax|vat|gst|tva|mwst|ust|netto|nettobetrag|gesamtbetrag|montant|importe|"
    r"item|description|qty|quantity|amount|unit\s*price|price"
    r")",
    re.IGNORECASE,
)
_LINE_HAS_COLON_VALUE = re.compile(r".+:\s*\S")   # "Label: value"
_LINE_MOSTLY_DIGITS = re.compile(r"^[\d\s\-/.,+()]+$")


def _is_bad_supplier_line(line: str) -> bool:
    """Return True if this line must not be used as the supplier name."""
    if _LINE_IS_LABEL.search(line):
        return True
    if _LINE_HAS_COLON_VALUE.search(line):
        return True
    if _LINE_MOSTLY_DIGITS.match(line):
        return True
    # Reject if more than half the non-space characters are digits
    non_space = line.replace(" ", "")
    if non_space and sum(c.isdigit() for c in non_space) / len(non_space) > 0.5:
        return True
    return False


def _extract_supplier(pages: list[ParsedPage]) -> ExtractedField:
    # 1. Labelled "From/Seller"
    for page in pages[:2]:
        text = page.text
        m = _SUPPLIER_LABELS.search(text)
        if m:
            name = _norm_ws(m.group(1)).strip().strip(".,;:")
            if len(name) >= 3 and not _is_bad_supplier_line(name):
                evidence = _norm_ws(m.group(0))
                return _field(name, 0.80, evidence, page.page_no)

    # 2. Top-of-first-page heuristic: first safe non-empty line
    for page in pages[:1]:
        lines = [_norm_ws(ln) for ln in page.text.splitlines() if _norm_ws(ln)]
        # Prefer a line with a known company suffix
        for line in lines[:8]:
            if _is_bad_supplier_line(line):
                continue
            if _COMPANY_SUFFIXES.search(line):
                return _field(line, 0.70, line, page.page_no)
        # Fallback: first safe non-trivial line
        for line in lines[:8]:
            if _is_bad_supplier_line(line):
                continue
            if len(line) >= 4:
                return _field(line, 0.55, line, page.page_no)

    return _empty_field()


# ---------------------------------------------------------------------------
# Customer (Bill To / Sold To / Client / Ship To)
# ---------------------------------------------------------------------------

_CUSTOMER_LABELS = re.compile(
    r"(?:bill(?:ed)?\s*to|sold\s*to|ship(?:ped)?\s*to|client|"
    r"customer|destinataire|rechnungsempfänger|cliente|"
    r"facturé\s*à|adressé\s*à)\s*[:\s]*"
    r"([A-Z][^\n]{2,60})",
    re.IGNORECASE,
)


def _extract_customer(pages: list[ParsedPage]) -> ExtractedField:
    for page in pages[:2]:
        text = page.text
        m = _CUSTOMER_LABELS.search(text)
        if m:
            name = _norm_ws(m.group(1)).strip().strip(".,;:")
            if len(name) >= 3:
                evidence = _norm_ws(m.group(0))
                return _field(name, 0.82, evidence, page.page_no)
    return _empty_field()


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

def _extract_currency(pages: list[ParsedPage]) -> tuple[ExtractedField, list[str]]:
    """Return (currency ExtractedField, extra_notes)."""
    for page in pages:
        cr: CurrencyResult = detect_currency(page.text)
        if cr.currency is not None:
            evidence = _find_currency_evidence(cr.currency, page.text)
            return _field(cr.currency, 0.85, evidence, page.page_no), []
        if "CURRENCY_AMBIGUOUS" in cr.notes:
            # bare $
            evidence = _find_bare_dollar_evidence(page.text)
            return _field(None, 0.0, None, None), ["CURRENCY_AMBIGUOUS"]
    return _empty_field(), []


def _find_currency_evidence(iso: str, text: str) -> str | None:
    sym_map = {"EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹", "BDT": "৳"}
    sym = sym_map.get(iso)
    if sym and sym in text:
        idx = text.find(sym)
        return _norm_ws(text[max(0, idx - 10):idx + 20])
    m = re.search(r"\b" + re.escape(iso) + r"\b", text, re.IGNORECASE)
    if m:
        return _norm_ws(text[max(0, m.start() - 10):m.end() + 20])
    return None


def _find_bare_dollar_evidence(text: str) -> str | None:
    idx = text.find("$")
    if idx >= 0:
        return _norm_ws(text[max(0, idx - 5):idx + 15])
    return None


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------

# Matches rows like: "Widget Pro  2  $9.99  $19.98"
_LINE_ITEM_RE = re.compile(
    r"^(?P<desc>[A-Za-z0-9][^\t\r\n]{1,80}?)"
    r"\s{2,}"
    r"(?P<qty>[\d,. ]+?)"
    r"\s{1,}"
    r"(?P<unit>[€$£¥₹৳]?\s*[\d,. ]+)"
    r"\s{1,}"
    r"(?P<amt>[€$£¥₹৳]?\s*[\d,. ]+)$",
    re.MULTILINE,
)

# Alternative: tab-separated
_LINE_ITEM_TAB = re.compile(
    r"^(?P<desc>[^\t\r\n]{1,80}?)\t+"
    r"(?P<qty>[\d,. ]+)\t+"
    r"(?P<unit>[€$£¥₹৳]?\s*[\d,. ]+)\t+"
    r"(?P<amt>[€$£¥₹৳]?\s*[\d,. ]+)$",
    re.MULTILINE,
)

# Table-header sentinel to find the items section
_ITEMS_HEADER = re.compile(
    r"\b(?:description|item|service|product|particulars|detail|qty|quantity|unit\s*price|amount|total)\b",
    re.IGNORECASE,
)


def _parse_line_items(pages: list[ParsedPage]) -> list[ExtractedLineItem]:
    items: list[ExtractedLineItem] = []
    for page in pages:
        text = page.text
        # Only scan text below a header-like line
        header_m = _ITEMS_HEADER.search(text)
        scan_text = text[header_m.start():] if header_m else text

        for pattern in (_LINE_ITEM_RE, _LINE_ITEM_TAB):
            for m in pattern.finditer(scan_text):
                desc = _norm_ws(m.group("desc")).strip()
                qty = parse_decimal(m.group("qty").strip())
                unit = parse_decimal(m.group("unit").strip())
                amt = parse_decimal(m.group("amt").strip())
                if desc and amt:
                    evidence = _norm_ws(m.group(0))
                    items.append(ExtractedLineItem(
                        description=desc,
                        quantity=qty,
                        unit_price=unit,
                        amount=amt,
                        confidence=0.75,
                        evidence=evidence,
                        page=page.page_no,
                    ))
            if items:
                break  # prefer first pattern that matched

    # Deduplicate by evidence
    seen: set[str] = set()
    deduped: list[ExtractedLineItem] = []
    for item in items:
        key = item.evidence or item.description or ""
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


# ---------------------------------------------------------------------------
# Confidence bonuses
# ---------------------------------------------------------------------------

_ABS_TOL = Decimal("0.02")


def _apply_consistency_bonuses(
    subtotal: ExtractedField,
    tax: ExtractedField,
    total: ExtractedField,
    line_items: list[ExtractedLineItem],
) -> tuple[ExtractedField, ExtractedField, ExtractedField]:
    """Apply +0.1 bonus when subtotal + tax ≈ total, and when line items sum ≈ subtotal."""
    try:
        st = Decimal(subtotal.value) if subtotal.value else None
        tx = Decimal(tax.value) if tax.value else None
        tot = Decimal(total.value) if total.value else None

        if st is not None and tx is not None and tot is not None:
            if abs(st + tx - tot) <= _ABS_TOL:
                subtotal = subtotal.model_copy(update={"confidence": _round_conf(min(1.0, subtotal.confidence + 0.1))})
                tax = tax.model_copy(update={"confidence": _round_conf(min(1.0, tax.confidence + 0.1))})
                total = total.model_copy(update={"confidence": _round_conf(min(1.0, total.confidence + 0.1))})

        if st is not None and line_items:
            item_sum = sum(Decimal(it.amount) for it in line_items if it.amount)
            if abs(item_sum - st) <= _ABS_TOL:
                subtotal = subtotal.model_copy(update={"confidence": _round_conf(min(1.0, subtotal.confidence + 0.1))})

    except (InvalidOperation, TypeError):
        pass

    return subtotal, tax, total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_by_rules(pages: list[ParsedPage]) -> ExtractionResult:
    """Run rules-only extraction over a list of parsed pages.

    Returns an ExtractionResult with method='rules'.
    """
    invoice_number = _extract_invoice_number(pages)
    invoice_date = _extract_invoice_date(pages)
    supplier_name = _extract_supplier(pages)
    customer_name = _extract_customer(pages)
    subtotal = _best_money_match(_SUBTOTAL_PAT, pages, 0.80)
    tax = _best_money_match(_TAX_PAT, pages, 0.80)
    total = _best_money_match(_TOTAL_PAT, pages, 0.82)
    currency_field, notes = _extract_currency(pages)
    line_items = _parse_line_items(pages)

    subtotal, tax, total = _apply_consistency_bonuses(subtotal, tax, total, line_items)

    return ExtractionResult(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        supplier_name=supplier_name,
        customer_name=customer_name,
        subtotal=subtotal,
        tax=tax,
        total=total,
        currency=currency_field,
        line_items=line_items,
        method=ExtractionMethod.RULES,
        notes=notes,
    )

