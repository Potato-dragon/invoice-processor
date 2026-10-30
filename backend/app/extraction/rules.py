"""Rules-based field extractor for invoices and receipts.

Extracts: invoice_number, invoice_date, supplier_name, customer_name,
subtotal, tax, total, currency, line_items.

Works line by line, because PDF text layers and OCR often put a label and its
value on separate lines ("Total:" then "$137.50") and table cells one per
line. A label's value is taken from the rest of its line, or from the next
line when the rest is empty. Bilingual labels ("TVA / Tax (18%):") are
handled by taking the text after the last colon.

Every field is an ExtractedField: value, confidence, evidence, page. The
evidence is copied from the page text so grounding can verify it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.contracts import (
    ExtractedField,
    ExtractedLineItem,
    ExtractionMethod,
    ExtractionResult,
    ParsedPage,
)
from app.extraction.normalize import detect_currency, parse_date, parse_decimal

# ---------------------------------------------------------------------------
# Small helpers
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


@dataclass(eq=False)
class _Line:
    page: int
    idx: int  # index within the page's cells, in reading order
    text: str
    right: "_Line | None" = None  # next cell on the same visual row (OCR rows are tab-separated)
    below: "_Line | None" = None  # cell in the same column on the next row


def _lines(pages: list[ParsedPage]) -> list[list[_Line]]:
    """One _Line per cell. Text-layer lines are single cells; OCR rows may hold
    several cells separated by tabs (see parsing.ocr)."""
    out = []
    for p in pages:
        rows = []
        for raw in (p.text or "").splitlines():
            cells = [_norm_ws(c) for c in raw.split("\t")]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
        flat: list[_Line] = []
        grid: list[list[_Line]] = []
        for cells in rows:
            row = []
            for c in cells:
                ln = _Line(p.page_no, len(flat), c)
                flat.append(ln)
                row.append(ln)
            for a, b in zip(row, row[1:]):
                a.right = b
            grid.append(row)
        for upper, lower in zip(grid, grid[1:]):
            if len(upper) > 1 and len(upper) == len(lower):
                for a, b in zip(upper, lower):
                    a.below = b
        out.append(flat)
    return out


def _followers(page_lines: list[_Line], line: _Line) -> list[_Line]:
    """Cells that may hold a label's value, nearest first: to the right,
    directly below, then simply the next line."""
    out: list[_Line] = []
    seq = page_lines[line.idx + 1] if line.idx + 1 < len(page_lines) else None
    for cand in (line.right, line.below, seq):
        if cand is not None and cand not in out:
            out.append(cand)
    return out


def _next(page_lines: list[_Line], line: _Line) -> _Line | None:
    found = _followers(page_lines, line)
    return found[0] if found else None


def _evidence(label: _Line, value: _Line) -> str:
    """Evidence must appear verbatim in the page text (after whitespace
    normalisation): label + value when they are adjacent, else the value alone."""
    if label.right is value or (label.below is None and value.idx == label.idx + 1):
        return f"{label.text} {value.text}"
    return value.text


def _remainder(text: str, label_end: int) -> str:
    """Text after a label: after the last colon if there is one, else the rest."""
    rest = text[label_end:]
    if ":" in rest:
        rest = rest[rest.rindex(":") + 1:]
    return rest.strip(" \t-–—#.|")


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

_CUR_TOKEN = r"(?:US\$|C\$|A\$|Rs\.?|Tk\.?|[$€£¥₹৳]|USD|EUR|GBP|JPY|INR|BDT|CHF|CAD|AUD)"
_NUM = r"\d{1,3}(?:[,.'   ]\d{2,3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEY_FULL = re.compile(rf"^\(?\s*-?\s*(?:{_CUR_TOKEN}\s*)?-?\s*(?P<num>{_NUM})\s*(?:{_CUR_TOKEN})?\s*\)?\s*-?$", re.IGNORECASE)
_MONEY_TOKEN = re.compile(rf"(?:{_CUR_TOKEN}\s*)?-?\s*(?P<num>{_NUM})(?:\s*{_CUR_TOKEN})?", re.IGNORECASE)
_PERCENT = re.compile(r"\(?\s*@?\s*\d+(?:[.,]\d+)?\s*%\s*\)?")
_PAREN_WORDS = re.compile(r"\([^)0-9]*\)")


def _money_from(text: str, strict: bool) -> str | None:
    """Parse a money value. strict=True (value on the next line) rejects bare
    small integers such as a table row number."""
    t = _PAREN_WORDS.sub(" ", _PERCENT.sub(" ", text)).strip()
    if not t:
        return None
    # OCR slip: "19,047,00" / "1.234.56" (same separator for thousands and
    # cents). Two digits after the last separator are the cents.
    t = re.sub(r"(\d{1,3}(?:,\d{3})+),(\d{2})(?!\d)", r"\1.\2", t)
    t = re.sub(r"(\d{1,3}(?:\.\d{3})+)\.(\d{2})(?!\d)", r"\1,\2", t)
    m = _MONEY_FULL.match(t)
    if m is None:
        return None
    looks_money = bool(re.search(r"[.,]\d{1,2}\s*\)?\s*(?:" + _CUR_TOKEN + r")?\s*$", t, re.IGNORECASE)) or bool(
        re.search(_CUR_TOKEN, t, re.IGNORECASE)) or bool(re.search(r"\d[,.' ]\d{3}", t))
    if strict and not looks_money:
        return None
    return parse_decimal(t)


_SUBTOTAL_LABEL = re.compile(
    r"^(?:sub[\s-]?total(?:\s+amount)?|net\s+(?:amount|total)|total\s+(?:hors\s+taxes?|ht\b|net\b|excl\.?(?:uding)?\s+(?:tax|vat))|"
    r"montant\s+ht|total\s+before\s+tax|nettobetrag|netto(?:summe)?|zwischensumme|summe\s+netto|base\s+imponible|importe\s+neto)",
    re.IGNORECASE,
)
_TAX_LABEL = re.compile(
    r"^(?:total\s+(?:tax|vat|gst)|(?:sales\s+|value\s+added\s+|estimated\s+|est\.?\s+)?tax(?:es)?|vat|gst|hst|pst|tva|mwst|ust|iva|igv|"
    r"steuer|umsatzsteuer|mehrwertsteuer|taxe)"
    r"(?!\s*(?:id\b|reg|ref|no\b|nr\b|number|#|code|date|invoice|identification|registration|intra|point|exempt|ident))",
    re.IGNORECASE,
)
_TOTAL_STRONG = re.compile(
    r"^(?:grand\s+total|total\s+(?:amount\s+)?due|amount\s+due|balance\s+due|total\s+(?:ttc|toutes\s+taxes)|total\s+payable|"
    r"amount\s+payable|total\s+a\s+pagar|importe\s+total|montant\s+(?:total|ttc|d[uû])|gesamtbetrag|gesamtsumme|endbetrag|"
    r"rechnungsbetrag|total\s+amount|total\s+incl|total\s+to\s+pay|invoice\s+total)",
    re.IGNORECASE,
)
_TOTAL_WEAK = re.compile(r"^(?:total|summe|betrag|importe|montant)\b(?!\s*(?:qty|quantity|items?|units?|weight|pages?|discount|savings))", re.IGNORECASE)


@dataclass
class _MoneyHit:
    value: str
    evidence: str
    page: int
    conf: float
    strength: int
    order: int


def _money_hits(all_lines: list[list[_Line]]) -> dict[str, list[_MoneyHit]]:
    hits: dict[str, list[_MoneyHit]] = {"subtotal": [], "tax": [], "total": []}
    order = 0
    for page_lines in all_lines:
        for line in page_lines:
            text = line.text
            kind, strength, m = None, 0, None
            if (m := _SUBTOTAL_LABEL.match(text)):
                kind = "subtotal"
            elif (m := _TAX_LABEL.match(text)):
                kind = "tax"
            elif (m := _TOTAL_STRONG.match(text)):
                kind, strength = "total", 2
            elif (m := _TOTAL_WEAK.match(text)):
                kind, strength = "total", 1
            if kind is None:
                continue
            rest = _remainder(text, m.end())
            value = _money_from(rest, strict=False) if rest else None
            evidence, conf = text, 0.85
            if value is None and not re.search(r"\d", _PERCENT.sub("", rest)):
                # Only the nearest cell: a value further away belongs to something else.
                nxt = _next(page_lines, line)
                if nxt is not None:
                    value = _money_from(nxt.text, strict=True)
                    evidence, conf = _evidence(line, nxt), 0.82
            if value is None:
                continue
            order += 1
            hits[kind].append(_MoneyHit(value, evidence, line.page, conf, strength, order))
    return hits


def _pick_money(hits: dict[str, list[_MoneyHit]]) -> tuple[ExtractedField, ExtractedField, ExtractedField]:
    def as_field(h: _MoneyHit | None) -> ExtractedField:
        return _field(h.value, h.conf, h.evidence, h.page) if h else _empty_field()

    sub = hits["subtotal"][0] if hits["subtotal"] else None
    tax = hits["tax"][0] if hits["tax"] else None
    totals = hits["total"]
    total = None
    if totals:
        # Prefer a total that equals subtotal + tax; else strongest label, last one.
        if sub is not None:
            expected = Decimal(sub.value) + (Decimal(tax.value) if tax else Decimal("0"))
            matching = [t for t in totals if abs(Decimal(t.value) - expected) <= _ABS_TOL]
            if matching:
                total = max(matching, key=lambda t: (t.strength, t.order))
        if total is None:
            total = max(totals, key=lambda t: (t.strength, t.order))
    return as_field(sub), as_field(tax), as_field(total)


# ---------------------------------------------------------------------------
# Invoice number
# ---------------------------------------------------------------------------

_INV_NUM_REJECTS = re.compile(
    r"^(?:data|date|number|no|num|ref|invoice|receipt|bill|order|"
    r"from|to|page|amount|total|tax|vat|currency|subtotal|net)s?$",
    re.IGNORECASE,
)
_INV_LABEL_STRONG = re.compile(
    r"(?:^|[\s/|(])(?:"
    r"(?:invoice|inv|bill|receipt|facture|factura|fattura|rechnung|recibo|ticket|transaction|txn)\s*"
    r"(?:no\b\.?|n[°ºo]\.?|num(?:ber|ero|éro)?\b\.?|nr\b\.?|#|id\b|ref(?:erence)?\b)|"
    r"rechnungs?-?\s*(?:nr\b\.?|nummer)|rechnungsnummer|n[°º]\s*(?:de\s+)?facture|num[ée]ro\s+(?:de\s+)?facture|"
    r"n[úu]mero\s+(?:de\s+)?factura|invoice\s*(?=:)"
    r")",
    re.IGNORECASE,
)
_INV_LABEL_WEAK = re.compile(r"(?:^|[\s/|])(?:doc(?:ument)?\s*(?:ref(?:erence)?|no\b\.?|number|#)|ref(?:erence)?\s*(?:no\b\.?|number|#)?)", re.IGNORECASE)
_INV_WEAK_BLOCK = re.compile(r"^(?:tax|vat|client|customer|order|po\b|purchase|supplier|vendor|account|bank|iban)", re.IGNORECASE)
_INV_TOKEN = re.compile(r"^#?\s*([A-Z0-9](?:[A-Z0-9\-/_.]{0,38}[A-Z0-9])?)\b", re.IGNORECASE)


def _inv_token(text: str) -> str | None:
    text = text.strip()
    # OCR often reads a leading "I" as "[" or "|" ("[NV-2026-001").
    text = re.sub(r"^[\[|](?=[A-Z]{1,3}[-/]?\d)", "I", text)
    m = _INV_TOKEN.match(text)
    if not m:
        return None
    tok = m.group(1).rstrip(".")
    if len(tok) < 2 or not re.search(r"\d", tok) or _INV_NUM_REJECTS.match(tok):
        return None
    if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}", tok):
        return None  # a date, not a number
    return tok


def _extract_invoice_number(all_lines: list[list[_Line]]) -> ExtractedField:
    for pattern, conf, blocked in ((_INV_LABEL_STRONG, 0.88, None), (_INV_LABEL_WEAK, 0.75, _INV_WEAK_BLOCK)):
        for page_lines in all_lines:
            for line in page_lines:
                m = pattern.search(line.text)
                if not m or (blocked and blocked.match(line.text)):
                    continue
                rest = _remainder(line.text, m.end())
                tok = _inv_token(rest) if rest else None
                evidence = line.text
                if tok is None and not rest:
                    nxt = _next(page_lines, line)
                    if nxt is not None:
                        tok = _inv_token(nxt.text)
                        evidence = _evidence(line, nxt)
                if tok:
                    return _field(tok, conf, evidence, line.page)
    return _empty_field()


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------

_MONTH = r"[A-Za-zÀ-ÿ]{3,10}\.?"
_DATE_TOKEN = re.compile(
    r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    rf"|\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?[\s.\-/]+(?:de\s+)?{_MONTH}[\s.,\-/]+(?:de\s+)?\d{{2,4}}"
    rf"|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})",
    re.IGNORECASE,
)
_DATE_LABEL = re.compile(
    r"(?:^|[\s/|])(?:invoice\s+date|date\s+of\s+(?:issue|invoice)|issue\s+date|date\s+issued|issued(?:\s+on)?|billing\s+date|"
    r"bill\s+date|tax\s+date|tax\s+point|receipt\s+date|transaction\s+date|sale\s+date|"
    r"date\s+d['’]?(?:émission|emission|facture)|date\s+de\s+facture|rechnungsdatum|ausstellungsdatum|"
    r"fecha(?:\s+de\s+(?:factura|emisi[óo]n))?|datum|date)\b",
    re.IGNORECASE,
)
_NOT_INVOICE_DATE = re.compile(r"due|échéance|echeance|fällig|vencimiento|payment|zahlbar|deliver|liefer|ship|order\s+date|period|valid|expir|generated|printed", re.IGNORECASE)
_US_HINT = re.compile(r"\bUSA\b|United States|\b[A-Z]{2}\s\d{5}(?:-\d{4})?\b|\bUSD\b|US\$")


def _day_first_hint(all_lines: list[list[_Line]]) -> bool:
    """Decide dd/mm vs mm/dd for ambiguous dates from other dates and locale cues."""
    text = "\n".join(ln.text for page in all_lines for ln in page)
    for m in re.finditer(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", text):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            return True
        if b > 12 >= a:
            return False
    head = "\n".join(ln.text for ln in (all_lines[0][:8] if all_lines else []))
    return not _US_HINT.search(head)


def _to_iso(raw: str, day_first: bool) -> tuple[str | None, bool]:
    """Return (iso date or impossible-date string, ambiguous)."""
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", raw)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        ambiguous = a <= 12 and b <= 12 and a != b
        d, mo = (a, b) if (day_first or a > 12) and b <= 12 else (b, a)
        if mo > 12:
            d, mo = mo, d
        dr = parse_date(f"{y:04d}-{mo:02d}-{d:02d}")
        if dr.iso_date:
            return dr.iso_date, ambiguous
        # Impossible date (e.g. 31/02/2026): keep it so validation can flag it.
        return (f"{y:04d}-{mo:02d}-{d:02d}" if 1 <= mo <= 12 and 1 <= d <= 31 else None), False
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        dr = parse_date(f"{y:04d}-{mo:02d}-{d:02d}")
        if dr.iso_date:
            return dr.iso_date, False
        return (f"{y:04d}-{mo:02d}-{d:02d}" if 1 <= mo <= 12 and 1 <= d <= 31 else None), False
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE).replace(" de ", " ")
    dr = parse_date(cleaned)
    return dr.iso_date, False


def _date_from(text: str, day_first: bool) -> tuple[str, str, bool] | None:
    m = _DATE_TOKEN.search(text)
    if not m:
        return None
    iso, ambiguous = _to_iso(m.group(1), day_first)
    return (iso, m.group(1), ambiguous) if iso else None


def _extract_invoice_date(all_lines: list[list[_Line]]) -> ExtractedField:
    day_first = _day_first_hint(all_lines)
    for page_lines in all_lines:
        for line in page_lines:
            m = _DATE_LABEL.search(line.text)
            if not m or _NOT_INVOICE_DATE.search(line.text[: m.end() + 1]) or _NOT_INVOICE_DATE.search(line.text.split(":")[0]):
                continue
            rest = _remainder(line.text, m.end())
            got = _date_from(rest, day_first) if rest else None
            evidence = line.text
            if got is None and not rest:
                nxt = _next(page_lines, line)
                if nxt is not None and not _NOT_INVOICE_DATE.search(nxt.text):
                    got = _date_from(nxt.text, day_first)
                    evidence = _evidence(line, nxt)
            if got:
                iso, _, ambiguous = got
                return _field(iso, 0.75 if ambiguous else 0.9, evidence, line.page)
    # Fallback: first date on the first page that is not a due/payment date.
    for line in all_lines[0] if all_lines else []:
        if _NOT_INVOICE_DATE.search(line.text):
            continue
        got = _date_from(line.text, day_first)
        if got:
            return _field(got[0], 0.6, line.text, line.page)
    return _empty_field()


# ---------------------------------------------------------------------------
# Parties: supplier and customer
# ---------------------------------------------------------------------------

_COMPANY_SUFFIXES = re.compile(
    r"\b(?:Inc|LLC|L\.L\.C|Ltd|Limited|Corp|Corporation|Co|Company|GmbH|AG|KG|SAS|SARL|SL|S\.?A|SpA|S\.p\.A|Srl|BV|NV|Oy|AB|AS|ApS|"
    r"PLC|LLP|Pty|Pvt|KK|Group|Holdings|Industries|Solutions|Services|Enterprises)\b\.?",
    re.IGNORECASE,
)
_TITLE_LINE = re.compile(
    r"^(?:(?:tax|commercial|proforma|pro\s*forma|sales|final)?\s*(?:invoice|receipt|bill|statement)(?:\s+statement)?|"
    r"facture(?:\s*/\s*invoice)?|rechnung|factura|fattura|cash\s+receipt|sales\s+receipt|invoice\s*/\s*facture|original|copy|duplicate)$",
    re.IGNORECASE,
)
_SUPPLIER_LABEL = re.compile(
    r"^(?:from|seller|vendor|supplier|supplied\s+by|bill(?:ed)?\s+from|issued\s+by|sold\s+by|merchant|store|"
    r"de(?=\s*:)|émetteur|emetteur|expéditeur|fournisseur|vendeur|absender|verkäufer|lieferant|rechnungssteller|emisor|proveedor|vendedor)\b",
    re.IGNORECASE,
)
_CUSTOMER_LABEL = re.compile(
    r"^(?:[^:/]{0,30}/\s*)?(?:bill(?:ed)?\s+to|invoice\s+to|sold\s+to|client|customer|buyer|purchaser|destinataire|"
    r"factur[ée]\s+[àa]|adress[ée]\s+[àa]|rechnungsempf[äa]nger|kunde|empf[äa]nger|cliente|facturar\s+a|ship(?:ped)?\s+to|deliver\s+to)\b"
    r"(?!\s*(?:ref|tax|id\b|no\b|nr\b|number|#|information|info\b|details|vat|code|account|since|service|copy))",
    re.IGNORECASE,
)
_NOT_NAME = re.compile(
    r"@|www\.|https?://|\b(?:tel|phone|fax|mobile|email|e-mail|courriel|tél)\b|^\+?\d[\d\s().-]{6,}$|"
    r"\b(?:street|st\.|road|rd\.|avenue|ave\.|boulevard|blvd|suite|floor|lane|drive|way|plot|straße|strasse|rue|calle|"
    r"p\.?o\.?\s*box)\b|\b\d{5}\b",
    re.IGNORECASE,
)
_ANY_LABEL = re.compile(
    r"^(?:invoice|receipt|bill|date|due|tax|vat|gst|tva|total|subtotal|amount|balance|description|qty|quantity|"
    r"unit|price|rate|item|page|terms|payment|po\b|order|ref|client\s+ref|customer\s+tax|account|iban|swift|bank|"
    r"thank|notes?|generated|valid)\b",
    re.IGNORECASE,
)


def _is_name_line(text: str) -> bool:
    t = text.strip()
    if len(t) < 3 or len(t) > 80:
        return False
    if _TITLE_LINE.match(t) or _ANY_LABEL.match(t) or _NOT_NAME.search(t):
        return False
    if ":" in t:
        return False
    letters = sum(c.isalpha() for c in t)
    digits = sum(c.isdigit() for c in t)
    return letters >= 3 and digits <= letters / 3


def _party_from_label(all_lines: list[list[_Line]], pattern: re.Pattern[str], conf: float, pages: int = 2) -> ExtractedField:
    for page_lines in all_lines[:pages]:
        for line in page_lines:
            m = pattern.match(line.text)
            if not m:
                continue
            rest = _remainder(line.text, m.end())
            if rest and _is_name_line(rest):
                return _field(rest, conf, line.text, line.page)
            if not rest:
                # "From: | Client:" on one OCR row: the name sits in the cell below.
                for nxt in _followers(page_lines, line):
                    if _is_name_line(nxt.text):
                        return _field(nxt.text, conf, _evidence(line, nxt), line.page)
    return _empty_field()


def _extract_supplier(all_lines: list[list[_Line]]) -> ExtractedField:
    labelled = _party_from_label(all_lines, _SUPPLIER_LABEL, 0.8)
    if labelled.value:
        return labelled
    first = all_lines[0] if all_lines else []
    candidates: list[_Line] = []
    for line in first[:12]:
        if _CUSTOMER_LABEL.match(line.text):
            break  # everything after "Bill To" belongs to the customer
        if _is_name_line(line.text):
            candidates.append(line)
    for line in candidates:
        if _COMPANY_SUFFIXES.search(line.text):
            return _field(line.text, 0.75, line.text, line.page)
    if candidates:
        return _field(candidates[0].text, 0.6, candidates[0].text, candidates[0].page)
    return _empty_field()


# Printed placeholders that mean "no named customer" (walk-in / counter sales).
_PLACEHOLDER_CUSTOMER = re.compile(
    r"^(?:standard|individual|walk[\s-]?in|cash|counter|retail|general|private|one[\s-]?time|guest)\s+(?:customer|client|sale|buyer)s?(?:\s+sale)?$|"
    r"^(?:n/?a|none|-+)$",
    re.IGNORECASE,
)


def _extract_customer(all_lines: list[list[_Line]]) -> ExtractedField:
    found = _party_from_label(all_lines, _CUSTOMER_LABEL, 0.82)
    if found.value and _PLACEHOLDER_CUSTOMER.match(found.value.strip()):
        return _empty_field()
    return found


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

_SYMBOL_ISO = [("US$", "USD"), ("C$", "CAD"), ("A$", "AUD"), ("€", "EUR"), ("£", "GBP"), ("¥", "JPY"), ("₹", "INR"),
               ("৳", "BDT")]
_WORD_ISO = [(r"\bRs\.?(?=\s*\d)", "INR"), (r"\bTk\.?(?=\s*\d)", "BDT")]


def _currency_in(text: str) -> tuple[str, str] | None:
    """Explicit currency in a snippet: ISO code, unambiguous symbol, or Rs/Tk."""
    m = re.search(r"\b(USD|EUR|GBP|JPY|INR|BDT|CHF|CAD|AUD|NZD|SGD|SEK|NOK|DKK|PLN|ZAR|CNY|HKD)\b", text)
    if m:
        return m.group(1), m.group(0)
    for sym, iso in _SYMBOL_ISO:
        if sym in text:
            return iso, sym
    for pat, iso in _WORD_ISO:
        mm = re.search(pat, text)
        if mm:
            return iso, mm.group(0)
    return None


def _extract_currency(pages: list[ParsedPage], all_lines: list[list[_Line]], total: ExtractedField) -> tuple[ExtractedField, list[str]]:
    """Return (currency ExtractedField, extra_notes)."""
    # 1. The total's own evidence ("Total: €1.234,56" or "Total Due: USD 99.00").
    if total.evidence:
        found = _currency_in(total.evidence)
        if found:
            return _field(found[0], 0.88, total.evidence, total.page), []
    # 2. A "Currency: EUR" line or any explicit code/symbol in the document.
    for page_lines in all_lines:
        for line in page_lines:
            found = _currency_in(line.text)
            if found:
                return _field(found[0], 0.85, line.text, line.page), []
    # 3. Words (euro, pounds ...) or a bare "$" (ambiguous, DECISIONS 11).
    for page in pages:
        cr = detect_currency(page.text)
        if cr.currency is not None:
            word = next((ln.text for ln in (all_lines[pages.index(page)] if all_lines else []) if detect_currency(ln.text).currency), None)
            if word:
                return _field(cr.currency, 0.75, word, page.page_no), []
        if "CURRENCY_AMBIGUOUS" in cr.notes:
            return _empty_field(), ["CURRENCY_AMBIGUOUS"]
    return _empty_field(), []


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------

_M = rf"\(?-?(?:{_CUR_TOKEN}\s*)?-?\d[\d,.'  ]*(?:[.,]\d{{1,2}})(?:\s*{_CUR_TOKEN})?\)?"
_SAME_LINE_ITEM = re.compile(
    rf"^(?P<desc>[A-Za-zÀ-ÿ][^\t]{{1,90}}?)\s+(?P<qty>\d+(?:[.,]\d{{1,3}})?)\s*(?:x|×|@|pcs|hrs?|units?)?\s+"
    rf"(?:x\s+|@\s+)?(?P<unit>{_M})\s+(?P<amt>{_M})$",
    re.IGNORECASE,
)
_HEADER_COLS = [
    ("index", re.compile(r"^(?:#|line\s*#|no\.?|s/?n|sl\.?\s*no\.?|item\s*#|pos\.?)$", re.IGNORECASE)),
    ("desc", re.compile(r"^(?:(?:item\s+)?description|items?|services?(?:\s*/\s*products?)?|products?|particulars|details|"
                        r"désignation|designation|bezeichnung|artikel|leistung|concepto|descripci[óo]n|article)$", re.IGNORECASE)),
    ("qty", re.compile(r"^(?:qty|quantity|units?|hrs|hours|qt[ée]|quantit[ée]|menge|anzahl|cantidad|pcs)$", re.IGNORECASE)),
    ("unit", re.compile(r"^(?:unit\s*(?:price|cost)|price|rate|prix(?:\s+unit(?:aire|\.)?)?|p\.?u\.?|einzelpreis|preis|precio(?:\s+unitario)?)$", re.IGNORECASE)),
    ("amount", re.compile(r"^(?:amount|total|line\s*total|total\s*amount|montant(?:\s+ht)?|betrag|gesamt(?:preis)?|importe|net\s+amount)$", re.IGNORECASE)),
]


def _header_col(text: str) -> str | None:
    for part in [text] + [p.strip() for p in text.split("/")]:
        for name, pat in _HEADER_COLS:
            if pat.match(part):
                return name
    return None


def _num(text: str, money: bool) -> str | None:
    t = text.strip()
    if money:
        return _money_from(t, strict=False) if re.search(r"\d", t) else None
    m = re.fullmatch(r"(\d+(?:[.,]\d{1,3})?)\s*(?:x|pcs|hrs?|units?|kg|h)?", t, re.IGNORECASE)
    return parse_decimal(m.group(1)) if m else None


def _column_items(page_lines: list[_Line]) -> list[ExtractedLineItem]:
    # Find a run of header cells (e.g. "#", "Description", "Qty", "Unit Price", "Amount").
    for start in range(len(page_lines)):
        cols: list[str] = []
        j = start
        while j < len(page_lines) and len(cols) < 6:
            c = _header_col(page_lines[j].text)
            if c is None or c in cols:
                break
            cols.append(c)
            j += 1
        if {"desc", "amount"} <= set(cols) and len(cols) >= 3:
            break
    else:
        return []
    k = len(cols)
    items: list[ExtractedLineItem] = []
    i = j
    while i + k <= len(page_lines):
        group = page_lines[i: i + k]
        if any(_SUBTOTAL_LABEL.match(g.text) or _TAX_LABEL.match(g.text) or _TOTAL_STRONG.match(g.text) or _TOTAL_WEAK.match(g.text) for g in group):
            break
        vals: dict[str, str | None] = {}
        ok = True
        for col, cell in zip(cols, group):
            if col == "desc":
                ok = bool(re.search(r"[A-Za-zÀ-ÿ]{2}", cell.text))
                vals["description"] = cell.text
            elif col == "index":
                ok = bool(re.fullmatch(r"\d{1,3}\.?", cell.text))
            elif col == "qty":
                vals["quantity"] = _num(cell.text, money=False)
                ok = vals["quantity"] is not None
            elif col == "unit":
                vals["unit_price"] = _num(cell.text, money=True)
                ok = vals["unit_price"] is not None
            else:
                vals["amount"] = _num(cell.text, money=True)
                ok = vals["amount"] is not None
            if not ok:
                break
        if not ok:
            break
        items.append(ExtractedLineItem(confidence=0.8, evidence=" ".join(g.text for g in group), page=group[0].page,
                                       description=vals.get("description"), quantity=vals.get("quantity"),
                                       unit_price=vals.get("unit_price"), amount=vals.get("amount")))
        i += k
    return items


def _parse_line_items(all_lines: list[list[_Line]]) -> list[ExtractedLineItem]:
    items: list[ExtractedLineItem] = []
    for page_lines in all_lines:
        col = _column_items(page_lines)
        if col:
            items.extend(col)
            continue
        for line in page_lines:
            if _SUBTOTAL_LABEL.match(line.text) or _TAX_LABEL.match(line.text) or _TOTAL_STRONG.match(line.text) or _TOTAL_WEAK.match(line.text):
                continue
            m = _SAME_LINE_ITEM.match(line.text)
            if not m:
                continue
            amt = _money_from(m.group("amt"), strict=False)
            if amt is None:
                continue
            items.append(ExtractedLineItem(
                description=m.group("desc").strip(), quantity=parse_decimal(m.group("qty")),
                unit_price=_money_from(m.group("unit"), strict=False), amount=amt,
                confidence=0.75, evidence=line.text, page=line.page,
            ))
    return items


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

        if st is not None and tot is not None and abs(st + (tx or Decimal("0")) - tot) <= _ABS_TOL:
            subtotal = subtotal.model_copy(update={"confidence": _round_conf(min(1.0, subtotal.confidence + 0.1))})
            if tx is not None:
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
    all_lines = _lines(pages)
    invoice_number = _extract_invoice_number(all_lines)
    invoice_date = _extract_invoice_date(all_lines)
    supplier_name = _extract_supplier(all_lines)
    customer_name = _extract_customer(all_lines)
    subtotal, tax, total = _pick_money(_money_hits(all_lines))
    currency_field, notes = _extract_currency(pages, all_lines, total)
    line_items = _parse_line_items(all_lines)

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
