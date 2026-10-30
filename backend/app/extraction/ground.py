"""Grounding: ensures every non-null extracted value has evidence that
actually appears in the page text.

If evidence text is absent (after whitespace normalization), the field's
value is set to null, confidence to 0, and 'EVIDENCE_NOT_FOUND:<field>'
is added to notes.
"""
from __future__ import annotations

import re

from app.contracts import (
    ExtractedField,
    ExtractedLineItem,
    ExtractionResult,
    ParsedPage,
)

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def _evidence_found(evidence: str | None, pages: list[ParsedPage]) -> bool:
    """Return True if evidence substring appears in any page text."""
    if not evidence:
        return False
    ev_norm = _norm(evidence)
    if not ev_norm:
        return False
    # Whole-word match: "Total: 100.00" must not be found inside "Subtotal: 100.00".
    pattern = re.compile(r"(?<![0-9a-zà-ÿ])" + re.escape(ev_norm) + r"(?![0-9a-zà-ÿ])")
    for page in pages:
        if pattern.search(_norm(page.text)):
            return True
    return False


def _ground_field(field: ExtractedField, field_name: str, pages: list[ParsedPage]) -> tuple[ExtractedField, str | None]:
    """Return (grounded_field, optional_note)."""
    if field.value is None:
        return field, None
    if _evidence_found(field.evidence, pages):
        return field, None
    # Evidence missing — null out
    nulled = ExtractedField(value=None, confidence=0.0, evidence=None, page=None)
    note = f"EVIDENCE_NOT_FOUND:{field_name}"
    return nulled, note


def ground_result(result: ExtractionResult, pages: list[ParsedPage]) -> ExtractionResult:
    """Run grounding on all fields of an ExtractionResult.

    Any field whose evidence text cannot be found in the page corpus is
    nulled with a note 'EVIDENCE_NOT_FOUND:<field>'.
    """
    notes = list(result.notes)
    updates: dict[str, ExtractedField] = {}

    scalar_fields = [
        "invoice_number", "invoice_date", "supplier_name", "customer_name",
        "subtotal", "tax", "total", "currency",
    ]
    for fname in scalar_fields:
        field: ExtractedField = getattr(result, fname)
        grounded, note = _ground_field(field, fname, pages)
        updates[fname] = grounded
        if note:
            notes.append(note)

    # Ground line items
    grounded_items: list[ExtractedLineItem] = []
    for item in result.line_items:
        if item.evidence and not _evidence_found(item.evidence, pages):
            # Drop item whose evidence doesn't exist in page text
            notes.append("EVIDENCE_NOT_FOUND:line_item")
        else:
            grounded_items.append(item)

    return result.model_copy(update={**updates, "line_items": grounded_items, "notes": notes})
