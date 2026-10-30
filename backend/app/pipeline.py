"""Stage runner: parse -> extract -> validate -> index, one RQ job per stage.

Each stage is idempotent (it replaces its own output), writes STARTED and
SUCCEEDED/FAILED processing events with duration, and enqueues the next stage.
A PipelineError fails the document at once with its code; any other error is
retried by RQ with backoff and fails as INTERNAL_ERROR when retries run out.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.contracts import (
    DocumentStatus,
    ErrorCode,
    ExtractionMethod,
    ExtractionResult,
    IssueModel,
    IssueSeverity,
    PageMethod,
    ParsedPage,
    PipelineError,
    ProcessingEventType,
    ReviewStatus,
    Stage,
)
from app.db import SessionLocal
from app.models import Document, Invoice, InvoiceLineItem, LedgerEntry, Page, ProcessingEvent, ValidationIssue

logger = logging.getLogger(__name__)

NEXT_STAGE = {Stage.PARSE: Stage.EXTRACT, Stage.EXTRACT: Stage.VALIDATE, Stage.VALIDATE: Stage.INDEX, Stage.INDEX: None}
STAGE_STATUS = {
    Stage.PARSE: DocumentStatus.PARSING, Stage.EXTRACT: DocumentStatus.EXTRACTING,
    Stage.VALIDATE: DocumentStatus.VALIDATING, Stage.INDEX: DocumentStatus.INDEXING,
}
SCALAR_FIELDS = ("invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency")


# --------------------------------------------------------------------------- helpers


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() and abs(d) < Decimal("1e14") else None


def _clip(value: str | None, n: int) -> str | None:
    return value[:n] if value else value


def event(session: Session, doc_id: uuid.UUID, stage: str, kind: ProcessingEventType, *, invoice_id=None,  # noqa: ANN001
          error_code: str | None = None, detail: dict | None = None, duration_ms: int | None = None) -> None:
    session.add(ProcessingEvent(document_id=doc_id, invoice_id=invoice_id, stage=stage, event=kind.value,
                                error_code=error_code, detail=detail or {}, duration_ms=duration_ms))


def load_pages(session: Session, doc_id: uuid.UUID) -> dict[int, ParsedPage]:
    rows = session.execute(select(Page).where(Page.document_id == doc_id).order_by(Page.page_no)).scalars()
    return {
        p.page_no: ParsedPage(page_no=p.page_no, text=p.text or "", method=PageMethod(p.method),
                              ocr_confidence=float(p.ocr_confidence) if p.ocr_confidence is not None else None,
                              width=p.width, height=p.height)
        for p in rows
    }


def invoice_pages(pages: dict[int, ParsedPage], inv: Invoice) -> list[ParsedPage]:
    return [pages[n] for n in range(inv.page_start, inv.page_end + 1) if n in pages]


def _invoices(session: Session, doc_id: uuid.UUID) -> list[Invoice]:
    return list(session.execute(select(Invoice).where(Invoice.document_id == doc_id).order_by(Invoice.page_start)).scalars())


# --------------------------------------------------------------------------- stages


def stage_parse(session: Session, doc: Document) -> dict[str, Any]:
    from app.parsing import parse_document

    path = Path(get_settings().storage_dir) / doc.storage_key
    if not path.is_file():
        raise PipelineError(ErrorCode.STORAGE_ERROR, "stored file is missing")
    parsed = parse_document(str(path), doc.kind)

    # Idempotent: replace everything this stage produced before.
    session.execute(delete(Invoice).where(Invoice.document_id == doc.id))
    session.execute(delete(Page).where(Page.document_id == doc.id))
    session.execute(delete(LedgerEntry).where(LedgerEntry.document_id == doc.id))
    session.execute(delete(ValidationIssue).where(ValidationIssue.document_id == doc.id))

    session.bulk_save_objects([
        Page(document_id=doc.id, page_no=p.page_no, text=p.text.replace("\x00", ""), method=p.method.value,
             ocr_confidence=p.ocr_confidence, width=p.width, height=p.height)
        for p in parsed.pages
    ])
    for start, end in parsed.invoice_ranges:
        session.add(Invoice(document_id=doc.id, page_start=start, page_end=end,
                            review_status=ReviewStatus.PENDING.value, extraction={}))
    session.bulk_save_objects([
        LedgerEntry(document_id=doc.id, sheet_name=r.sheet_name[:255], row_no=r.row_no,
                    invoice_number=_clip(r.invoice_number, 255), invoice_date=r.invoice_date,
                    supplier_name=_clip(r.supplier_name, 512), customer_name=_clip(r.customer_name, 512),
                    subtotal=_dec(r.subtotal), tax=_dec(r.tax), total=_dec(r.total), currency=r.currency, raw=r.raw)
        for r in parsed.ledger_rows
    ])
    doc.page_count = len(parsed.pages) or None
    methods = Counter(p.method.value for p in parsed.pages)
    return {"pages": len(parsed.pages), "methods": dict(methods), "invoices": len(parsed.invoice_ranges),
            "ledger_rows": len(parsed.ledger_rows), "warnings": parsed.warnings[:50]}


def apply_extraction(session: Session, inv: Invoice, result: ExtractionResult) -> None:
    data = result.model_dump(mode="json")
    inv.extraction = data
    inv.invoice_number = _clip(result.invoice_number.value, 255)
    inv.invoice_date = (result.invoice_date.value or None) and result.invoice_date.value[:10]
    inv.supplier_name = _clip(result.supplier_name.value, 512)
    inv.customer_name = _clip(result.customer_name.value, 512)
    inv.subtotal = _dec(result.subtotal.value)
    inv.tax = _dec(result.tax.value)
    inv.total = _dec(result.total.value)
    cur = result.currency.value
    inv.currency = cur.upper() if cur and len(cur) == 3 else None
    inv.extraction_method = data["method"]
    session.execute(delete(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id))
    session.bulk_save_objects([
        InvoiceLineItem(invoice_id=inv.id, line_no=i + 1, description=li.description,
                        quantity=_dec(li.quantity), unit_price=_dec(li.unit_price), amount=_dec(li.amount))
        for i, li in enumerate(result.line_items)
    ])


VISION_MAX_PAGES = 2   # first and last page of an invoice (header + totals)
VISION_MAX_SIDE = 2000  # px; keeps image tokens and upload size small
VISION_DPI = 150


def page_images_for(doc: Document, page_nos: list[int]) -> list[tuple[int, bytes]]:
    """Render pages of the stored file to PNG for the vision fallback."""
    import io

    from PIL import Image, ImageSequence

    wanted = sorted({page_nos[0], page_nos[-1]})[:VISION_MAX_PAGES] if page_nos else []
    path = Path(get_settings().storage_dir) / doc.storage_key
    out: list[tuple[int, bytes]] = []

    def png(img: Image.Image) -> bytes:
        img = img.convert("L")
        if max(img.size) > VISION_MAX_SIDE:
            img.thumbnail((VISION_MAX_SIDE, VISION_MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    if doc.kind == "pdf":
        import pymupdf

        with pymupdf.open(path) as pdf:
            for n in wanted:
                pix = pdf.load_page(n - 1).get_pixmap(dpi=VISION_DPI, colorspace=pymupdf.csGRAY)
                out.append((n, png(Image.frombytes("L", (pix.width, pix.height), pix.samples))))
    elif doc.kind == "image":
        with Image.open(path) as img:
            for i, frame in enumerate(ImageSequence.Iterator(img), start=1):
                if i in wanted:
                    out.append((i, png(frame.copy())))
    return out


def stage_extract(session: Session, doc: Document) -> dict[str, Any]:
    from app.extraction import extract_invoice

    pages = load_pages(session, doc.id)
    methods: Counter[str] = Counter()
    for inv in _invoices(session, doc.id):
        nos = list(range(inv.page_start, inv.page_end + 1))
        result = extract_invoice(invoice_pages(pages, inv), session_factory=SessionLocal,
                                 page_images=lambda nos=nos: page_images_for(doc, nos))
        apply_extraction(session, inv, result)
        methods[inv.extraction_method or "rules"] += 1
    llm = sum(v for k, v in methods.items() if k.startswith("llm"))
    return {"invoices": sum(methods.values()), "methods": dict(methods), "llm_invoices": llm}


def _issue_rows(doc_id: uuid.UUID, inv_id: uuid.UUID, issues: list[IssueModel], resolved: set[tuple[str, str | None]]) -> list[ValidationIssue]:
    rows = []
    for i in issues:
        code = i.code.value if hasattr(i.code, "value") else i.code
        sev = i.severity.value if hasattr(i.severity, "value") else i.severity
        rows.append(ValidationIssue(document_id=doc_id, invoice_id=inv_id, code=code, severity=sev, field=i.field,
                                    message=i.message, details=i.details, resolved=(code, i.field) in resolved))
    return rows


def refresh_review_status(session: Session, inv: Invoice) -> None:
    errors = session.execute(
        select(ValidationIssue.id).where(ValidationIssue.invoice_id == inv.id, ValidationIssue.severity == IssueSeverity.ERROR.value,
                                         ValidationIssue.resolved.is_(False)).limit(1)
    ).first()
    if errors:
        inv.review_status = ReviewStatus.NEEDS_REVIEW.value
    elif inv.review_status in (ReviewStatus.CORRECTED.value,) or inv.extraction_method == ExtractionMethod.MANUAL.value:
        inv.review_status = ReviewStatus.CORRECTED.value
    else:
        inv.review_status = ReviewStatus.AUTO_OK.value


def validate_one(session: Session, doc: Document, inv: Invoice, pages: list[ParsedPage]) -> list[IssueModel]:
    from app.validation import DbDuplicateLookup, validate_invoice

    if not inv.extraction:
        return []
    ex = ExtractionResult.model_validate(inv.extraction)
    session.flush()
    issues = validate_invoice(ex, pages, DbDuplicateLookup(session, inv.id, older_than=(doc.created_at, doc.id, inv.page_start)))
    old = session.execute(select(ValidationIssue).where(ValidationIssue.invoice_id == inv.id)).scalars().all()
    resolved = {(o.code, o.field) for o in old if o.resolved}
    # Cross-check issues come from POST /crosschecks/run and are kept.
    session.execute(delete(ValidationIssue).where(ValidationIssue.invoice_id == inv.id, ~ValidationIssue.code.startswith("CROSS_")))
    session.add_all(_issue_rows(doc.id, inv.id, issues, resolved))
    session.flush()
    refresh_review_status(session, inv)
    flag_newer_duplicates(session, doc, inv)
    return issues


def flag_newer_duplicates(session: Session, doc: Document, inv: Invoice) -> None:
    """Order-independent duplicate detection.

    An invoice is only flagged against *older* ones. If a newer copy was
    validated before this one had its fields (parallel workers), flag it now.
    """
    from app.validation import DbDuplicateLookup, ExistingInvoice, InMemoryDuplicateLookup
    from app.validation.checks import check_duplicates

    if not inv.supplier_name or (not inv.invoice_number and inv.total is None):
        return
    me = ExistingInvoice(str(inv.id), inv.supplier_name, inv.invoice_number, inv.total, inv.invoice_date)
    newer = DbDuplicateLookup(session, inv.id, newer_than=(doc.created_at, doc.id, inv.page_start))
    for cand in newer.find_candidates(inv.supplier_name, inv.invoice_number, inv.total, inv.invoice_date):
        other = session.get(Invoice, uuid.UUID(cand.id))
        if other is None or not other.extraction or other.review_status == ReviewStatus.PENDING.value:
            continue  # not validated yet; it will see this invoice itself
        found = check_duplicates(ExtractionResult.model_validate(other.extraction), InMemoryDuplicateLookup([me]))
        existing_codes = {c for (c,) in session.execute(select(ValidationIssue.code).where(ValidationIssue.invoice_id == other.id))}
        new = [i for i in found if i.code.value not in existing_codes]
        if not new:
            continue
        session.add_all(_issue_rows(other.document_id, other.id, new, set()))
        session.flush()
        refresh_review_status(session, other)
        other_doc = session.get(Document, other.document_id)
        if other_doc and other_doc.status == DocumentStatus.COMPLETED.value:
            other_doc.status = DocumentStatus.NEEDS_REVIEW.value


def stage_validate(session: Session, doc: Document) -> dict[str, Any]:
    pages = load_pages(session, doc.id)
    sev: Counter[str] = Counter()
    for inv in _invoices(session, doc.id):
        for i in validate_one(session, doc, inv, invoice_pages(pages, inv)):
            sev[i.severity.value if hasattr(i.severity, "value") else i.severity] += 1
    return {"issues": dict(sev)}


def _search_text(inv: Invoice) -> str:
    items = [li.get("description") or "" for li in (inv.extraction or {}).get("line_items", [])][:20]
    parts = [inv.supplier_name, "invoice", inv.invoice_number, "to", inv.customer_name, inv.invoice_date,
             "total", str(inv.total) if inv.total is not None else None, inv.currency, ". Items:", "; ".join(items)]
    return " ".join(p for p in parts if p)


def index_invoices(session: Session, invoices: list[Invoice], pages: dict[int, ParsedPage]) -> None:
    from app.embeddings import embed

    if not invoices:
        return
    vectors = embed([_search_text(inv) for inv in invoices])
    for inv, vec in zip(invoices, vectors):
        body = " ".join(p.text for p in invoice_pages(pages, inv))[:20000]
        session.execute(
            text("UPDATE invoices SET fts = setweight(to_tsvector('simple', :head), 'A') || to_tsvector('simple', :body) WHERE id = :id"),
            {"head": _search_text(inv), "body": body, "id": inv.id},
        )
        inv.embedding = vec


def stage_index(session: Session, doc: Document) -> dict[str, Any]:
    invoices = _invoices(session, doc.id)
    index_invoices(session, invoices, load_pages(session, doc.id))
    return {"invoices": len(invoices)}


STAGES: dict[Stage, Callable[[Session, Document], dict[str, Any]]] = {
    Stage.PARSE: stage_parse, Stage.EXTRACT: stage_extract, Stage.VALIDATE: stage_validate, Stage.INDEX: stage_index,
}


def refresh_document_status(session: Session, doc: Document) -> None:
    """After a reviewer action: lock the document, then recompute its status if
    processing has finished. If a stage is still running, it waits for this
    commit and sees the change when it finalizes."""
    session.flush()
    session.refresh(doc, with_for_update=True)
    if doc.status in (DocumentStatus.COMPLETED.value, DocumentStatus.NEEDS_REVIEW.value):
        finalize_status(session, doc)


def finalize_status(session: Session, doc: Document) -> None:
    # Lock the document row and re-read it, so a reviewer's action and the end of
    # the index stage cannot overwrite each other's result (lost update).
    session.flush()
    session.refresh(doc, with_for_update=True)
    review = session.execute(
        select(Invoice.id).where(Invoice.document_id == doc.id, Invoice.review_status == ReviewStatus.NEEDS_REVIEW.value).limit(1)
    ).first()
    doc.status = (DocumentStatus.NEEDS_REVIEW if review else DocumentStatus.COMPLETED).value


# --------------------------------------------------------------------------- runner


def _retries_left() -> int:
    try:
        from rq import get_current_job

        job = get_current_job()
        return int(job.retries_left or 0) if job is not None else 0
    except Exception:  # noqa: BLE001
        return 0


def _fail(doc_id: uuid.UUID, stage: Stage, code: str, message: str, started: float) -> None:
    with SessionLocal() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            return
        doc.status = DocumentStatus.FAILED.value
        doc.current_stage = stage.value
        doc.error_code = code
        doc.error_message = message[:2000]
        event(session, doc_id, stage.value, ProcessingEventType.FAILED, error_code=code,
              detail={"message": message[:500]}, duration_ms=int((time.perf_counter() - started) * 1000))
        session.commit()


def run_stage(document_id: str, stage_name: str) -> None:
    from app.jobs import enqueue_stage

    stage = Stage(stage_name)
    doc_id = uuid.UUID(document_id)
    with SessionLocal() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            logger.warning("document %s vanished; skipping %s", document_id, stage.value)
            return
        doc.status = STAGE_STATUS[stage].value
        doc.current_stage = stage.value
        doc.error_code = doc.error_message = None
        event(session, doc_id, stage.value, ProcessingEventType.STARTED)
        session.commit()

    started = time.perf_counter()
    try:
        with SessionLocal() as session:
            doc = session.get(Document, doc_id)
            detail = STAGES[stage](session, doc)
            nxt = NEXT_STAGE[stage]
            if nxt is None:
                finalize_status(session, doc)
            event(session, doc_id, stage.value, ProcessingEventType.SUCCEEDED, detail=detail,
                  duration_ms=int((time.perf_counter() - started) * 1000))
            session.commit()
    except PipelineError as exc:
        _fail(doc_id, stage, exc.code.value, exc.message, started)
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("stage %s failed for %s", stage.value, document_id)
        if _retries_left() > 0:
            with SessionLocal() as session:
                event(session, doc_id, stage.value, ProcessingEventType.RETRIED,
                      detail={"message": f"{type(exc).__name__}: {str(exc)[:300]}"})
                session.commit()
            raise
        _fail(doc_id, stage, ErrorCode.INTERNAL_ERROR.value, f"{type(exc).__name__}: {exc}", started)
        return
    if nxt is not None:
        enqueue_stage(document_id, nxt)
