"""Search (keyword / semantic / hybrid), cross-checks and stats."""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import Float, and_, case, cast, delete, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.api.deps import ApiError, iso, money, rate_limit
from app.api.documents import invoice_summary
from app.contracts import CrosscheckKind, DocumentStatus, ErrorCode
from app.db import get_session
from app.models import Crosscheck, Document, Invoice, LedgerEntry, ProcessingEvent, ValidationIssue
from app.pipeline import _issue_rows, finalize_status, refresh_review_status

router = APIRouter()
_RRF_K = 60
_CANDIDATES = 200


def _filters(supplier, currency, date_from, date_to, min_total, max_total, review_status, document_id) -> list:  # noqa: ANN001
    conds = []
    if supplier:
        conds.append(Invoice.supplier_name.ilike(f"%{supplier}%"))
    if currency:
        conds.append(Invoice.currency == currency.upper())
    if date_from:
        conds.append(Invoice.invoice_date >= date_from)
    if date_to:
        conds.append(Invoice.invoice_date <= date_to)
    for value, op in ((min_total, "ge"), (max_total, "le")):
        if value is None or value == "":
            continue
        try:
            d = Decimal(value)
        except InvalidOperation:
            raise ApiError(400, ErrorCode.BAD_REQUEST, f"'{value}' is not a number") from None
        conds.append(Invoice.total >= d if op == "ge" else Invoice.total <= d)
    if review_status:
        conds.append(Invoice.review_status.in_(review_status.split(",")))
    if document_id:
        try:
            conds.append(Invoice.document_id == uuid.UUID(document_id))
        except ValueError:
            raise ApiError(400, ErrorCode.BAD_REQUEST, "document_id is not a valid id") from None
    return conds


def _keyword(session: Session, q: str, conds: list) -> list[tuple[uuid.UUID, float]]:
    tsq = func.websearch_to_tsquery("simple", q)
    like = f"%{q}%"
    exact = or_(Invoice.invoice_number.ilike(like), Invoice.supplier_name.ilike(like), Invoice.customer_name.ilike(like))
    score = func.coalesce(func.ts_rank(Invoice.fts, tsq), 0) + case((exact, 1.0), else_=0.0)
    stmt = (select(Invoice.id, score.label("score")).where(and_(or_(Invoice.fts.op("@@")(tsq), exact), *conds))
            .order_by(score.desc(), Invoice.id).limit(_CANDIDATES))
    return [(r.id, float(r.score)) for r in session.execute(stmt)]


def _semantic(session: Session, q: str, conds: list) -> list[tuple[uuid.UUID, float]]:
    from app.embeddings import embed_query

    vec = "[" + ",".join(f"{x:.6f}" for x in embed_query(q)) + "]"  # floats only: safe to inline
    dist = Invoice.embedding.op("<->")(literal_column(f"'{vec}'::vector"))
    stmt = (select(Invoice.id, cast(dist, Float).label("dist")).where(Invoice.embedding.is_not(None), *conds)
            .order_by(dist).limit(_CANDIDATES))
    # Unit vectors: cosine similarity = 1 - d^2 / 2.
    return [(r.id, round(1 - r.dist * r.dist / 2, 4)) for r in session.execute(stmt)]


@router.get("/search", dependencies=[Depends(rate_limit("search"))])
def search(q: str | None = None, mode: str = "hybrid", supplier: str | None = None, currency: str | None = None,
           date_from: str | None = None, date_to: str | None = None, min_total: str | None = None, max_total: str | None = None,
           review_status: str | None = None, document_id: str | None = None,
           limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0),
           session: Session = Depends(get_session)) -> dict[str, Any]:
    if mode not in ("keyword", "semantic", "hybrid"):
        raise ApiError(400, ErrorCode.BAD_REQUEST, "mode must be keyword, semantic or hybrid")
    conds = _filters(supplier, currency, date_from, date_to, min_total, max_total, review_status, document_id)
    q = (q or "").strip()
    if not q:
        base = select(Invoice).where(*conds)
        total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()
        rows = session.execute(base.order_by(Invoice.created_at.desc(), Invoice.page_start).limit(limit).offset(offset)).scalars().all()
        ranked = [(r.id, None) for r in rows]
        by_id = {r.id: r for r in rows}
    else:
        if mode == "keyword":
            scored = _keyword(session, q, conds)
        elif mode == "semantic":
            scored = _semantic(session, q, conds)
        else:
            fused: dict[uuid.UUID, float] = {}
            for results in (_keyword(session, q, conds), _semantic(session, q, conds)):
                for rank, (iid, _) in enumerate(results):
                    fused[iid] = fused.get(iid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            scored = sorted(fused.items(), key=lambda kv: (-kv[1], str(kv[0])))
            scored = [(i, round(s, 5)) for i, s in scored]
        total = len(scored)
        ranked = scored[offset: offset + limit]
        ids = [i for i, _ in ranked]
        by_id = {r.id: r for r in session.execute(select(Invoice).where(Invoice.id.in_(ids))).scalars()} if ids else {}
    docs = {d.id: d for d in session.execute(select(Document).where(Document.id.in_({r.document_id for r in by_id.values()}))).scalars()} if by_id else {}
    items = []
    for iid, score in ranked:
        inv = by_id.get(iid)
        if inv is None:
            continue
        d = docs.get(inv.document_id)
        items.append({**invoice_summary(inv), "score": score, "filename": d.filename if d else None})
    return {"items": items, "total": total, "limit": limit, "offset": offset, "mode": mode if q else "filter"}


# --------------------------------------------------------------------------- cross-checks


def _inv_dict(inv: Invoice) -> dict[str, Any]:
    return {"id": str(inv.id), "document_id": str(inv.document_id), "invoice_number": inv.invoice_number,
            "supplier_name": inv.supplier_name, "total": money(inv.total), "subtotal": money(inv.subtotal),
            "tax": money(inv.tax), "invoice_date": inv.invoice_date, "currency": inv.currency}


def _ledger_dict(r: LedgerEntry) -> dict[str, Any]:
    return {"id": str(r.id), "document_id": str(r.document_id), "sheet_name": r.sheet_name, "row_no": r.row_no,
            "invoice_number": r.invoice_number, "supplier_name": r.supplier_name, "total": money(r.total),
            "subtotal": money(r.subtotal), "tax": money(r.tax), "invoice_date": r.invoice_date, "currency": r.currency}


def _uuids(values: list[str] | None) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(v) for v in values or []]
    except ValueError:
        raise ApiError(400, ErrorCode.BAD_REQUEST, "ids must be valid UUIDs") from None


@router.post("/crosschecks/run", status_code=202)
def run_crosschecks(body: dict[str, Any] = Body(...), session: Session = Depends(get_session)) -> dict[str, Any]:
    """Compare invoices with other invoices (PDF_PDF) or with spreadsheet rows (PDF_EXCEL).

    left_ids: invoice ids (empty = all invoices). right_ids: invoice ids for
    PDF_PDF, spreadsheet document ids for PDF_EXCEL (empty = all). Runs
    inline (an O(n) dict match takes well under a second for thousands of rows).
    """
    from app.validation import crosscheck_batch, crosscheck_issues

    try:
        kind = CrosscheckKind(body.get("kind", ""))
    except ValueError:
        raise ApiError(400, ErrorCode.BAD_REQUEST, "kind must be PDF_PDF or PDF_EXCEL") from None
    left_ids, right_ids = _uuids(body.get("left_ids")), _uuids(body.get("right_ids"))
    lq = select(Invoice).where(Invoice.invoice_number.is_not(None))
    if left_ids:
        lq = lq.where(Invoice.id.in_(left_ids))
    lefts = session.execute(lq).scalars().all()
    if kind == CrosscheckKind.PDF_EXCEL:
        rq = select(LedgerEntry)
        if right_ids:
            rq = rq.where(LedgerEntry.document_id.in_(right_ids))
        rights = [_ledger_dict(r) for r in session.execute(rq).scalars()]
    else:
        rq = select(Invoice).where(Invoice.invoice_number.is_not(None))
        rq = rq.where(Invoice.id.in_(right_ids)) if right_ids else rq.where(Invoice.id.not_in([i.id for i in lefts]))
        rights = [_inv_dict(i) for i in session.execute(rq).scalars()]
    out = crosscheck_batch(kind, [_inv_dict(i) for i in lefts], rights)

    by_id = {str(i.id): i for i in lefts}
    code_for_kind = ("CROSS_EXCEL_MISMATCH" if kind == CrosscheckKind.PDF_EXCEL else "CROSS_PDF_MISMATCH", "CROSS_NO_MATCH")
    if lefts:
        session.execute(delete(ValidationIssue).where(ValidationIssue.invoice_id.in_([i.id for i in lefts]),
                                                      ValidationIssue.code.in_(code_for_kind)))
    counts = {"MATCH": 0, "MISMATCH": 0, "NO_MATCH": 0}
    results = []
    for res in out["results"]:
        counts[res.result.value if hasattr(res.result, "value") else res.result] += 1
        row = Crosscheck(kind=kind.value, left_ref=res.left_ref, right_ref=res.right_ref,
                         result=res.result.value if hasattr(res.result, "value") else res.result, details=res.details)
        session.add(row)
        inv = by_id.get(res.left_ref.get("id"))
        if inv is not None:
            session.add_all(_issue_rows(inv.document_id, inv.id, crosscheck_issues(res), set()))
        results.append({"left_ref": res.left_ref, "right_ref": res.right_ref, "result": row.result, "details": res.details})
    session.flush()
    touched_docs = set()
    for inv in lefts:
        refresh_review_status(session, inv)
        touched_docs.add(inv.document_id)
    for doc in session.execute(select(Document).where(Document.id.in_(touched_docs))).scalars() if touched_docs else []:
        if doc.status in (DocumentStatus.COMPLETED.value, DocumentStatus.NEEDS_REVIEW.value):
            finalize_status(session, doc)
    session.commit()
    return {"kind": kind.value, "summary": counts, "unmatched_right": out["unmatched_right"][:500],
            "unmatched_right_count": len(out["unmatched_right"]), "items": results[:1000]}


@router.get("/crosschecks")
def list_crosschecks(kind: str | None = None, result: str | None = None, limit: int = Query(100, ge=1, le=1000),
                     offset: int = Query(0, ge=0), session: Session = Depends(get_session)) -> dict[str, Any]:
    stmt = select(Crosscheck)
    if kind:
        stmt = stmt.where(Crosscheck.kind == kind)
    if result:
        stmt = stmt.where(Crosscheck.result == result)
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = session.execute(stmt.order_by(Crosscheck.created_at.desc(), Crosscheck.id).limit(limit).offset(offset)).scalars()
    items = [{"id": str(c.id), "kind": c.kind, "left_ref": c.left_ref, "right_ref": c.right_ref, "result": c.result,
              "details": c.details, "created_at": iso(c.created_at)} for c in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# --------------------------------------------------------------------------- stats


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict[str, Any]:
    by_status = dict(session.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    by_error = dict(session.execute(select(Document.error_code, func.count()).where(Document.error_code.is_not(None)).group_by(Document.error_code)).all())
    by_kind = dict(session.execute(select(Document.kind, func.count()).group_by(Document.kind)).all())
    review = dict(session.execute(select(Invoice.review_status, func.count()).group_by(Invoice.review_status)).all())
    methods = dict(session.execute(select(Invoice.extraction_method, func.count()).where(Invoice.extraction_method.is_not(None)).group_by(Invoice.extraction_method)).all())
    stage_rows = session.execute(select(ProcessingEvent.stage, func.count(), func.avg(ProcessingEvent.duration_ms), func.max(ProcessingEvent.duration_ms))
                                 .where(ProcessingEvent.event == "SUCCEEDED").group_by(ProcessingEvent.stage)).all()
    per_doc = (select(ProcessingEvent.document_id, func.sum(ProcessingEvent.duration_ms).label("ms"))
               .where(ProcessingEvent.event == "SUCCEEDED").group_by(ProcessingEvent.document_id).subquery())
    avg_doc_ms = session.execute(select(func.avg(per_doc.c.ms))).scalar()
    issues = dict(session.execute(select(ValidationIssue.code, func.count()).group_by(ValidationIssue.code)).all())
    total_docs = sum(by_status.values())
    done = by_status.get("COMPLETED", 0) + by_status.get("NEEDS_REVIEW", 0)
    return {
        "documents": {"total": total_docs, "by_status": by_status, "by_error_code": by_error, "by_kind": by_kind,
                      "success_rate": round(done / total_docs, 4) if total_docs else None,
                      "failure_rate": round(by_status.get("FAILED", 0) / total_docs, 4) if total_docs else None},
        "invoices": {"total": sum(review.values()), "by_review_status": review, "by_extraction_method": methods},
        "stages": {s: {"runs": n, "avg_ms": round(float(a or 0), 1), "max_ms": m} for s, n, a, m in stage_rows},
        "avg_document_processing_ms": round(float(avg_doc_ms), 1) if avg_doc_ms is not None else None,
        "issues_by_code": issues,
    }
