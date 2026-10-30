"""Per-invoice validation rules. Decimal only, deterministic, no network.

Severity follows DECISIONS.md item 11. Any error-level issue means the invoice
needs review; the stage runner (lane A) applies that status.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

from rapidfuzz import fuzz

from app.contracts import ExtractionResult, IssueCode, IssueModel, IssueSeverity, ParsedPage
from app.validation.lookup import DuplicateLookup, normalize_invoice_number, normalize_supplier

TOLERANCE = Decimal("0.02")
LOW_CONFIDENCE = 0.6
LOW_OCR_CONFIDENCE = 0.6
FUZZY_SUPPLIER_RATIO = 90
DUPLICATE_DATE_WINDOW_DAYS = 3

_REQUIRED_ERROR = ("invoice_number", "invoice_date", "supplier_name", "total")
_REQUIRED_INFO = ("customer_name", "tax")
_LABELS = {
    "invoice_number": "invoice number", "invoice_date": "invoice date", "supplier_name": "supplier name",
    "customer_name": "customer name", "subtotal": "subtotal", "tax": "tax", "total": "total", "currency": "currency",
}
_SCALARS = tuple(_LABELS)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _issue(code: IssueCode, severity: IssueSeverity, message: str, field: str | None = None, **details: Any) -> IssueModel:
    clean = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in details.items()}
    return IssueModel(code=code, severity=severity, field=field, message=message, details=clean)


def _value(extraction: ExtractionResult, name: str) -> str | None:
    return getattr(extraction, name).value


# --------------------------------------------------------------------------- field checks


def check_missing(ex: ExtractionResult) -> list[IssueModel]:
    issues = []
    for name in _REQUIRED_ERROR:
        if _value(ex, name) is None:
            issues.append(_issue(IssueCode.MISSING_FIELD, IssueSeverity.ERROR, f"The {_LABELS[name]} could not be found.", name))
    for name in _REQUIRED_INFO:
        if _value(ex, name) is not None:
            continue
        if name == "tax":
            sub, tot = _dec(ex.subtotal.value), _dec(ex.total.value)
            if sub is not None and tot is not None and abs(sub - tot) <= TOLERANCE:
                continue  # no tax charged: subtotal equals total
        issues.append(_issue(IssueCode.MISSING_FIELD, IssueSeverity.INFO, f"No {_LABELS[name]} on this document.", name))
    return issues


# --------------------------------------------------------------------------- arithmetic


def check_arithmetic(ex: ExtractionResult) -> list[IssueModel]:
    issues = []
    sub, tax, tot = _dec(ex.subtotal.value), _dec(ex.tax.value), _dec(ex.total.value)

    amounts = [_dec(li.amount) for li in ex.line_items]
    if ex.line_items and sub is not None and all(a is not None for a in amounts):
        lines_sum = sum(amounts, Decimal("0"))
        if abs(lines_sum - sub) > TOLERANCE:
            issues.append(_issue(
                IssueCode.LINE_ITEMS_SUBTOTAL_MISMATCH, IssueSeverity.ERROR,
                f"Line items add up to {lines_sum}, but the subtotal says {sub}.", "subtotal",
                line_items_sum=lines_sum, subtotal=sub, difference=lines_sum - sub,
            ))

    if sub is not None and tot is not None:
        expected = sub + (tax or Decimal("0"))
        if abs(expected - tot) > TOLERANCE:
            issues.append(_issue(
                IssueCode.SUBTOTAL_TAX_TOTAL_MISMATCH, IssueSeverity.ERROR,
                f"Subtotal {sub} plus tax {tax or 0} is {expected}, but the total says {tot}.", "total",
                subtotal=sub, tax=tax, expected_total=expected, total=tot, difference=tot - expected,
            ))

    for i, li in enumerate(ex.line_items):
        q, p, a = _dec(li.quantity), _dec(li.unit_price), _dec(li.amount)
        if q is None or p is None or a is None:
            continue
        if abs(q * p - a) > TOLERANCE:
            issues.append(_issue(
                IssueCode.LINE_ITEMS_SUBTOTAL_MISMATCH, IssueSeverity.WARNING,
                f"Line {i + 1}: {q} x {p} is {q * p}, but the line amount says {a}.", f"line_items[{i}]",
                quantity=q, unit_price=p, expected_amount=q * p, amount=a,
            ))
    return issues


# --------------------------------------------------------------------------- sanity


def check_sanity(ex: ExtractionResult, today: dt.date | None = None) -> list[IssueModel]:
    issues = []
    for name in ("subtotal", "tax", "total"):
        v = _dec(_value(ex, name))
        if v is not None and v < 0:
            issues.append(_issue(IssueCode.NEGATIVE_AMOUNT, IssueSeverity.ERROR, f"The {_LABELS[name]} is negative ({v}).", name, value=v))
    for i, li in enumerate(ex.line_items):
        a = _dec(li.amount)
        if a is not None and a < 0:
            issues.append(_issue(IssueCode.NEGATIVE_AMOUNT, IssueSeverity.ERROR, f"Line {i + 1} has a negative amount ({a}).", f"line_items[{i}]", value=a))

    raw_date = ex.invoice_date.value
    if raw_date is not None:
        try:
            d = dt.date.fromisoformat(raw_date)
        except ValueError:
            issues.append(_issue(IssueCode.INVALID_DATE, IssueSeverity.ERROR, f"The invoice date '{raw_date}' is not a real date.", "invoice_date", value=raw_date))
        else:
            today = today or dt.date.today()
            if d.year < 2000 or d > today + dt.timedelta(days=365):
                issues.append(_issue(IssueCode.INVALID_DATE, IssueSeverity.WARNING, f"The invoice date {raw_date} looks unlikely; please check it.", "invoice_date", value=raw_date))
    return issues


# --------------------------------------------------------------------------- quality


def check_quality(ex: ExtractionResult, pages: list[ParsedPage]) -> list[IssueModel]:
    issues = []
    for name in _SCALARS:
        f = getattr(ex, name)
        if f.value is not None and f.confidence < LOW_CONFIDENCE:
            if f"VISION_UNVERIFIED:{name}" in ex.notes:
                msg = f"The {_LABELS[name]} was read from the page image and could not be confirmed in the scanned text; please check it."
            else:
                msg = f"The {_LABELS[name]} was read with low confidence; please check it."
            issues.append(_issue(IssueCode.LOW_CONFIDENCE, IssueSeverity.WARNING, msg, name, confidence=f.confidence))
    for p in pages:
        if p.ocr_confidence is not None and p.ocr_confidence < LOW_OCR_CONFIDENCE:
            issues.append(_issue(IssueCode.LOW_OCR_CONFIDENCE, IssueSeverity.WARNING, f"Page {p.page_no} was hard to read (scan quality).", None, page=p.page_no, ocr_confidence=p.ocr_confidence))
    # Values read only from the page image could not be checked against any text:
    # one error per invoice so a person confirms them (DECISIONS 28). Marking it
    # checked, or correcting the fields, clears it.
    unverified = [n.split(":", 1)[1] for n in dict.fromkeys(ex.notes) if n.startswith("VISION_UNVERIFIED:")]
    unverified = [f for f in unverified if getattr(ex, f, None) is not None and getattr(ex, f).value is not None]
    if unverified:
        labels = ", ".join(_LABELS.get(f, f) for f in unverified)
        issues.append(_issue(IssueCode.LOW_CONFIDENCE, IssueSeverity.ERROR,
                             f"These values were read from the page image and could not be checked against the scanned text: {labels}. Please confirm them.",
                             None, fields=unverified, source="vision"))
    seen: set[str] = set()
    for note in ex.notes:
        if note in seen:
            continue
        seen.add(note)
        if note == "CURRENCY_AMBIGUOUS":
            issues.append(_issue(IssueCode.CURRENCY_AMBIGUOUS, IssueSeverity.ERROR, "The currency is shown only as '$'; please choose the currency.", "currency"))
        elif note.startswith("EVIDENCE_NOT_FOUND"):
            field = note.split(":", 1)[1] if ":" in note else None
            label = _LABELS.get(field or "", field or "a value")
            issues.append(_issue(IssueCode.EVIDENCE_NOT_FOUND, IssueSeverity.WARNING, f"A value for {label} was proposed but not found in the document text, so it was left empty.", field))
    return issues


# --------------------------------------------------------------------------- duplicates


def _days_apart(a: str | None, b: str | None) -> int | None:
    try:
        return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def check_duplicates(ex: ExtractionResult, lookup: DuplicateLookup | None) -> list[IssueModel]:
    if lookup is None:
        return []
    supplier, number, date = ex.supplier_name.value, ex.invoice_number.value, ex.invoice_date.value
    total = _dec(ex.total.value)
    if not supplier or (not number and total is None):
        return []
    n_sup, n_num = normalize_supplier(supplier), normalize_invoice_number(number)
    exact, fuzzy = [], []
    for c in lookup.find_candidates(supplier, number, total, date):
        c_sup = normalize_supplier(c.supplier_name)
        same_num = bool(n_num) and normalize_invoice_number(c.invoice_number) == n_num
        same_total = total is not None and c.total is not None and abs(Decimal(c.total) - total) <= TOLERANCE
        if c_sup == n_sup and same_num and same_total:
            exact.append(c.id)
            continue
        if fuzz.ratio(c_sup, n_sup) >= FUZZY_SUPPLIER_RATIO:
            days = _days_apart(c.invoice_date, date)
            if same_num or (same_total and days is not None and days <= DUPLICATE_DATE_WINDOW_DAYS):
                fuzzy.append(c.id)
    issues = []
    if exact:
        issues.append(_issue(IssueCode.DUPLICATE_EXACT, IssueSeverity.ERROR, "This invoice was already received (same supplier, number and total).", "invoice_number", matches=exact))
    if fuzzy:
        issues.append(_issue(IssueCode.DUPLICATE_FUZZY, IssueSeverity.ERROR, "This invoice looks very similar to one already received; please check it is not a duplicate.", "invoice_number", matches=fuzzy))
    return issues
