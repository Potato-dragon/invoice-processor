"""Vision fallback: let the LLM read the page *image* when OCR text is poor.

Why: the text-only cascade can never do better than the OCR it is given. On a
510 px wide invoice image Tesseract read 0 of 7 key fields while Gemma 4,
given the image, read 7 of 7 (measured 31 Oct 2026).

Trust rules (values cannot be grounded in unreadable OCR text):
- A vision value replaces the rules value only if the rules value is missing,
  below 0.7 confidence, or came from a page whose OCR confidence is below 0.6.
- If the value (or its evidence) is found in the OCR text, it is treated like
  any grounded value (confidence 0.8). Otherwise confidence is 0.55 and the
  note VISION_UNVERIFIED:<field> is added, which validation turns into a
  LOW_CONFIDENCE warning so a person checks it.
- Money values that add up (subtotal + tax = total) get +0.1 confidence.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from typing import Any

from app.contracts import ExtractedField, ExtractedLineItem, ExtractionResult, PageMethod, ParsedPage
from app.extraction.ground import _norm
from app.extraction.normalize import detect_currency, parse_date, parse_decimal

logger = logging.getLogger(__name__)

VISION_OCR_BELOW = 0.80     # use vision when any OCR page is below this confidence
GARBLED_OCR_BELOW = 0.60    # below this, rules values from OCR text are not trusted
SCALARS = ("invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency")
MONEY = {"subtotal", "tax", "total"}
PageImages = Callable[[], list[tuple[int, bytes]]]


def ocr_pages(pages: list[ParsedPage]) -> list[ParsedPage]:
    return [p for p in pages if p.method != PageMethod.TEXT_LAYER]


def min_ocr_confidence(pages: list[ParsedPage]) -> float | None:
    confs = [p.ocr_confidence or 0.0 for p in ocr_pages(pages)]
    return min(confs) if confs else None


def vision_needed(result: ExtractionResult, pages: list[ParsedPage], missing: list[str]) -> bool:
    """Only for scanned/image pages: low OCR confidence or required fields still missing."""
    low = min_ocr_confidence(pages)
    if low is None:
        return False  # digital text layer: the text is exact, the image adds nothing
    return low < VISION_OCR_BELOW or bool(missing)


def images_key(images: list[tuple[int, bytes]]) -> str:
    h = hashlib.sha256()
    for page_no, data in images:
        h.update(str(page_no).encode())
        h.update(data)
    return "images:" + h.hexdigest()


def normalize_value(field: str, value: Any) -> tuple[str | None, list[str]]:
    """Turn an LLM answer into the contract format. Returns (value, notes)."""
    if value is None:
        return None, []
    text = str(value).strip()
    if not text or text.lower() in ("null", "none", "n/a", "-"):
        return None, []
    if field in MONEY:
        return parse_decimal(text), []
    if field == "invoice_date":
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return text, []
        return parse_date(text).iso_date, []
    if field == "currency":
        if re.fullmatch(r"[A-Za-z]{3}", text):
            return text.upper(), []
        found = detect_currency(text)
        if found.currency:
            return found.currency, []
        return None, list(found.notes)  # e.g. a bare "$" -> CURRENCY_AMBIGUOUS
    if field == "invoice_number":
        text = text.lstrip("#№ ").strip()  # "# BLR_123" -> "BLR_123"
    return " ".join(text.split()), []


def _seen_in_text(field: str, value: str, evidence: str | None, pages: list[ParsedPage]) -> bool:
    corpus = " ".join(_norm(p.text) for p in pages)
    if evidence and _norm(evidence) in corpus:
        return True
    if field in MONEY:
        # Amounts are printed with separators: accept "3,458.00" / "3.458,00" / "3458.00".
        whole, _, cents = value.partition(".")
        digits = re.sub(r"\D", "", corpus)
        return len(whole) >= 2 and (whole + cents) in digits
    return _norm(value) in corpus


def merge_vision(base: ExtractionResult, data: dict[str, Any], pages: list[ParsedPage]) -> ExtractionResult:
    low = min_ocr_confidence(pages)
    garbled = low is not None and low < GARBLED_OCR_BELOW
    notes = list(base.notes)
    updates: dict[str, Any] = {}
    for field in SCALARS:
        raw = data.get(field)
        raw_value = raw.get("value") if isinstance(raw, dict) else raw
        evidence = raw.get("evidence") if isinstance(raw, dict) else None
        value, extra = normalize_value(field, raw_value)
        if extra and field == "currency":
            notes.extend(n for n in extra if n not in notes)
        if value is None:
            continue
        current: ExtractedField = getattr(base, field)
        if current.value is not None and current.confidence >= 0.7 and not garbled:
            continue  # a confident rules value wins
        verified = _seen_in_text(field, value, evidence, pages)
        page = raw.get("page") if isinstance(raw, dict) and isinstance(raw.get("page"), int) and raw["page"] > 0 else None
        ev = evidence if isinstance(evidence, str) and evidence.strip() else f"read from page image: {value}"
        updates[field] = ExtractedField(value=value, confidence=0.8 if verified else 0.55, evidence=ev[:300], page=page)
        notes = [n for n in notes if n != f"EVIDENCE_NOT_FOUND:{field}"]
        if not verified:
            notes.append(f"VISION_UNVERIFIED:{field}")
        if field == "currency":
            notes = [n for n in notes if n != "CURRENCY_AMBIGUOUS"]

    merged = base.model_copy(update={**updates, "notes": notes})
    sub, tax, tot = (merged.subtotal.value, merged.tax.value, merged.total.value)
    try:
        from decimal import Decimal

        if sub and tot and abs(Decimal(sub) + Decimal(tax or "0") - Decimal(tot)) <= Decimal("0.02"):
            for f in ("subtotal", "tax", "total"):
                fld = getattr(merged, f)
                if f in updates and fld.value is not None:
                    merged = merged.model_copy(update={f: fld.model_copy(update={"confidence": min(0.9, fld.confidence + 0.1)})})
    except Exception:  # noqa: BLE001 - malformed numbers just skip the bonus
        pass

    items = data.get("line_items")
    if isinstance(items, list) and items and (not base.line_items or garbled):
        parsed = []
        for it in items:
            if not isinstance(it, dict):
                continue
            amount = normalize_value("total", it.get("amount"))[0]
            if amount is None:
                continue
            parsed.append(ExtractedLineItem(
                description=(str(it.get("description")).strip() or None) if it.get("description") else None,
                quantity=normalize_value("total", it.get("quantity"))[0],
                unit_price=normalize_value("total", it.get("unit_price"))[0],
                amount=amount, confidence=0.55, evidence="read from page image", page=None,
            ))
        if parsed:
            merged = merged.model_copy(update={"line_items": parsed})
    return merged
