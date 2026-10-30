"""Invoice detail, manual corrections, issue review."""
from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ApiError, iso, money
from app.api.documents import invoice_summary
from app.contracts import (
    DocumentStatus,
    ErrorCode,
    ExtractedField,
    ExtractedLineItem,
    ExtractionMethod,
    ExtractionResult,
    ReviewStatus,
)
from app.db import get_session
from app.extraction.normalize import parse_date, parse_decimal
from app.models import Correction, Document, Invoice, InvoiceLineItem, ValidationIssue
from app.pipeline import (
    SCALAR_FIELDS,
    apply_extraction,
    finalize_status,
    index_invoices,
    invoice_pages,
    load_pages,
    refresh_review_status,
    validate_one,
)

router = APIRouter()
_MONEY = {"subtotal", "tax", "total"}


def _get_invoice(session: Session, inv_id: str) -> Invoice:
    try:
        uid = uuid.UUID(inv_id)
    except ValueError:
        raise ApiError(404, ErrorCode.NOT_FOUND, "invoice not found") from None
    inv = session.get(Invoice, uid)
    if inv is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "invoice not found")
    return inv


def issue_dict(i: ValidationIssue) -> dict[str, Any]:
    return {"id": str(i.id), "document_id": str(i.document_id), "invoice_id": str(i.invoice_id) if i.invoice_id else None,
            "code": i.code, "severity": i.severity, "field": i.field, "message": i.message, "details": i.details,
            "resolved": i.resolved, "created_at": iso(i.created_at)}


def invoice_detail(session: Session, inv: Invoice) -> dict[str, Any]:
    doc = session.get(Document, inv.document_id)
    items = session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id).order_by(InvoiceLineItem.line_no)).scalars()
    issues = session.execute(select(ValidationIssue).where(ValidationIssue.invoice_id == inv.id)
                             .order_by(ValidationIssue.resolved, ValidationIssue.severity, ValidationIssue.code)).scalars()
    corrections = session.execute(select(Correction).where(Correction.invoice_id == inv.id).order_by(Correction.created_at)).scalars()
    return {
        **invoice_summary(inv),
        "document": {"id": str(doc.id), "filename": doc.filename, "kind": doc.kind, "status": doc.status, "page_count": doc.page_count} if doc else None,
        "extraction": inv.extraction,
        "line_items": [{"line_no": li.line_no, "description": li.description, "quantity": money(li.quantity),
                        "unit_price": money(li.unit_price), "amount": money(li.amount)} for li in items],
        "issues": [issue_dict(i) for i in issues],
        "corrections": [{"field": c.field, "old_value": c.old_value, "new_value": c.new_value, "created_at": iso(c.created_at)} for c in corrections],
        "created_at": iso(inv.created_at), "updated_at": iso(inv.updated_at),
    }


@router.get("/invoices/{inv_id}")
def get_invoice(inv_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return invoice_detail(session, _get_invoice(session, inv_id))


def _normalize(field: str, value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ApiError(400, ErrorCode.BAD_REQUEST, f"{field}: value must be a string")
    raw = str(value).strip()
    if field in _MONEY:
        out = parse_decimal(raw)
        if out is None:
            raise ApiError(400, ErrorCode.BAD_REQUEST, f"{field}: '{raw}' is not a number")
        return out
    if field == "invoice_date":
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return raw
        out = parse_date(raw).iso_date
        if out is None:
            raise ApiError(400, ErrorCode.BAD_REQUEST, f"invoice_date: '{raw}' is not a date (use YYYY-MM-DD)")
        return out
    if field == "currency":
        if not re.fullmatch(r"[A-Za-z]{3}", raw):
            raise ApiError(400, ErrorCode.BAD_REQUEST, "currency: use a 3-letter ISO code such as USD or EUR")
        return raw.upper()
    return raw[:512]


def _line_items(value: Any) -> list[ExtractedLineItem]:
    if not isinstance(value, list):
        raise ApiError(400, ErrorCode.BAD_REQUEST, "line_items must be a list")
    out = []
    for n, li in enumerate(value):
        if not isinstance(li, dict):
            raise ApiError(400, ErrorCode.BAD_REQUEST, f"line_items[{n}] must be an object")
        vals = {k: _normalize("total" if k != "description" else "description", li.get(k)) for k in ("quantity", "unit_price", "amount")}
        out.append(ExtractedLineItem(description=(li.get("description") or None), confidence=1.0, evidence="manual correction", **vals))
    return out


def _empty_result() -> ExtractionResult:
    e = ExtractedField(confidence=0)
    return ExtractionResult(**{f: e for f in SCALAR_FIELDS}, method=ExtractionMethod.RULES)


@router.patch("/invoices/{inv_id}")
def correct_invoice(inv_id: str, body: dict[str, Any] = Body(...), session: Session = Depends(get_session)) -> dict[str, Any]:
    inv = _get_invoice(session, inv_id)
    allowed = set(SCALAR_FIELDS) | {"line_items"}
    unknown = set(body) - allowed
    if unknown or not body:
        raise ApiError(400, ErrorCode.BAD_REQUEST, f"fields you can correct: {', '.join(sorted(allowed))}")
    ex = ExtractionResult.model_validate(inv.extraction) if inv.extraction else _empty_result()
    updates: dict[str, Any] = {}
    notes = list(ex.notes)
    for field, value in body.items():
        if field == "line_items":
            items = _line_items(value)
            session.add(Correction(invoice_id=inv.id, field="line_items", old_value=str(len(ex.line_items)) + " items", new_value=str(len(items)) + " items"))
            updates["line_items"] = items
            continue
        new = _normalize(field, value)
        old = getattr(ex, field).value
        if new == old:
            continue
        session.add(Correction(invoice_id=inv.id, field=field, old_value=old, new_value=new))
        updates[field] = ExtractedField(value=new, confidence=1.0 if new is not None else 0.0,
                                        evidence="manual correction" if new is not None else None)
        notes = [n for n in notes if n != f"EVIDENCE_NOT_FOUND:{field}" and not (field == "currency" and n == "CURRENCY_AMBIGUOUS")]
    if not updates:
        return invoice_detail(session, inv)
    ex = ex.model_copy(update={**updates, "notes": notes, "method": ExtractionMethod.MANUAL})
    apply_extraction(session, inv, ex)
    inv.review_status = ReviewStatus.CORRECTED.value
    doc = session.get(Document, inv.document_id)
    pages = load_pages(session, doc.id)
    validate_one(session, doc, inv, invoice_pages(pages, inv))
    index_invoices(session, [inv], pages)
    if doc.status in (DocumentStatus.COMPLETED.value, DocumentStatus.NEEDS_REVIEW.value):
        finalize_status(session, doc)
    session.commit()
    return invoice_detail(session, inv)


@router.get("/issues")
def list_issues(severity: str | None = None, code: str | None = None, resolved: bool | None = None,
                document_id: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    stmt = select(ValidationIssue)
    if severity:
        stmt = stmt.where(ValidationIssue.severity.in_(severity.split(",")))
    if code:
        stmt = stmt.where(ValidationIssue.code.in_(code.split(",")))
    if resolved is not None:
        stmt = stmt.where(ValidationIssue.resolved.is_(resolved))
    if document_id:
        try:
            stmt = stmt.where(ValidationIssue.document_id == uuid.UUID(document_id))
        except ValueError:
            raise ApiError(400, ErrorCode.BAD_REQUEST, "document_id is not a valid id") from None
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = session.execute(stmt.order_by(ValidationIssue.created_at.desc(), ValidationIssue.id).limit(limit).offset(offset)).scalars().all()
    return {"items": [issue_dict(i) for i in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/issues/{issue_id}/resolve")
def resolve_issue(issue_id: str, body: dict[str, Any] = Body(default={}), session: Session = Depends(get_session)) -> dict[str, Any]:
    """Mark an issue as checked by a person (e.g. a duplicate that is not one)."""
    try:
        issue = session.get(ValidationIssue, uuid.UUID(issue_id))
    except ValueError:
        issue = None
    if issue is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "issue not found")
    issue.resolved = bool(body.get("resolved", True))
    session.flush()
    if issue.invoice_id:
        inv = session.get(Invoice, issue.invoice_id)
        refresh_review_status(session, inv)
        doc = session.get(Document, inv.document_id)
        if doc.status in (DocumentStatus.COMPLETED.value, DocumentStatus.NEEDS_REVIEW.value):
            finalize_status(session, doc)
    session.commit()
    return issue_dict(issue)
