"""Upload, list, detail, events, file download, pages, ledger, reprocess."""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ApiError, iso, money, rate_limit
from app.config import get_settings
from app.contracts import DocumentKind, DocumentStatus, ErrorCode, PipelineError, ProcessingEventType, Stage
from app.db import get_session
from app.filetypes import detect
from app.jobs import enqueue_stage
from app.models import Document, Invoice, LedgerEntry, Page, ProcessingEvent, ValidationIssue
from app.pipeline import event
from app.storage import LocalStorage

router = APIRouter()
_CHUNK = 1024 * 1024
_MAX_FILES = 500
_EXT_KIND = {"pdf": "pdf", "jpg": "image", "jpeg": "image", "png": "image", "tif": "image", "tiff": "image",
             "xlsx": "spreadsheet", "xls": "spreadsheet", "csv": "spreadsheet"}


def doc_summary(d: Document) -> dict[str, Any]:
    return {
        "id": str(d.id), "filename": d.filename, "mime": d.mime, "size_bytes": d.size_bytes, "kind": d.kind,
        "status": d.status, "current_stage": d.current_stage, "error_code": d.error_code, "error_message": d.error_message,
        "page_count": d.page_count, "sha256": d.sha256, "created_at": iso(d.created_at), "updated_at": iso(d.updated_at),
    }


def invoice_summary(inv: Invoice) -> dict[str, Any]:
    return {
        "id": str(inv.id), "document_id": str(inv.document_id), "page_start": inv.page_start, "page_end": inv.page_end,
        "review_status": inv.review_status, "invoice_number": inv.invoice_number, "invoice_date": inv.invoice_date,
        "supplier_name": inv.supplier_name, "customer_name": inv.customer_name, "subtotal": money(inv.subtotal),
        "tax": money(inv.tax), "total": money(inv.total), "currency": inv.currency, "extraction_method": inv.extraction_method,
    }


def _get_doc(session: Session, doc_id: str) -> Document:
    try:
        uid = uuid.UUID(doc_id)
    except ValueError:
        raise ApiError(404, ErrorCode.NOT_FOUND, "document not found") from None
    doc = session.get(Document, uid)
    if doc is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "document not found")
    return doc


def _check_pdf_limits(path: str) -> None:
    import pymupdf

    try:
        doc = pymupdf.open(path, filetype="pdf")
    except Exception:  # noqa: BLE001 - corrupt PDFs are reported by the parse stage
        return
    with doc:
        if doc.needs_pass:
            raise PipelineError(ErrorCode.FILE_ENCRYPTED, "PDF is password protected")
        if doc.page_count > get_settings().max_pages:
            raise PipelineError(ErrorCode.PAGE_LIMIT_EXCEEDED, f"PDF has {doc.page_count} pages; the limit is {get_settings().max_pages}")


def _ingest(session: Session, storage: LocalStorage, upload: UploadFile) -> dict[str, Any]:
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    filename = os.path.basename(upload.filename or "upload")[:1024] or "upload"
    sha = hashlib.sha256()
    size = 0
    head = b""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
        try:
            while chunk := upload.file.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    break
                if len(head) < 8192:
                    head += chunk[: 8192 - len(head)]
                sha.update(chunk)
                tmp.write(chunk)
        finally:
            tmp.flush()
    kind_guess = _EXT_KIND.get(filename.lower().rsplit(".", 1)[-1], DocumentKind.PDF.value)
    try:
        if size == 0:
            raise PipelineError(ErrorCode.FILE_EMPTY, "the file is empty")
        if size > max_bytes:
            raise PipelineError(ErrorCode.FILE_TOO_LARGE, f"file is larger than {settings.max_upload_mb} MB")
        with open(tmp_path, "rb") as fh:
            kind, mime = detect(head, filename, fh)
        if kind == DocumentKind.PDF:
            _check_pdf_limits(tmp_path)
        with open(tmp_path, "rb") as fh:
            key = storage.save(fh)
    except PipelineError as exc:
        doc = Document(filename=filename, mime=upload.content_type or "application/octet-stream", size_bytes=size,
                       sha256=sha.hexdigest(), storage_key=f"rejected-{uuid.uuid4().hex}", kind=kind_guess,
                       status=DocumentStatus.FAILED.value, current_stage=Stage.PARSE.value,
                       error_code=exc.code.value, error_message=exc.message)
        session.add(doc)
        session.flush()
        event(session, doc.id, Stage.PARSE.value, ProcessingEventType.FAILED, error_code=exc.code.value,
              detail={"message": exc.message, "at": "upload"})
        session.commit()
        return {"id": str(doc.id), "filename": filename, "status": doc.status,
                "error": {"code": exc.code.value, "message": exc.message}}
    finally:
        os.unlink(tmp_path)

    duplicate_of = session.execute(select(Document.id).where(Document.sha256 == sha.hexdigest(), Document.status != DocumentStatus.FAILED.value).limit(1)).scalar()
    doc = Document(filename=filename, mime=mime, size_bytes=size, sha256=sha.hexdigest(), storage_key=key,
                   kind=kind.value, status=DocumentStatus.UPLOADED.value)
    session.add(doc)
    session.commit()
    out = {"id": str(doc.id), "filename": filename, "status": doc.status, "kind": doc.kind}
    if duplicate_of:
        out["duplicate_of"] = str(duplicate_of)
    return out


@router.post("/documents", status_code=201, dependencies=[Depends(rate_limit("upload"))])
def upload(files: list[UploadFile] = File(...), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    if len(files) > _MAX_FILES:
        raise ApiError(400, ErrorCode.BAD_REQUEST, f"at most {_MAX_FILES} files per request")
    storage = LocalStorage(get_settings().storage_dir)
    results = [_ingest(session, storage, f) for f in files]
    # Enqueue only after every row is committed, so workers always find them.
    for r in results:
        if r["status"] == DocumentStatus.UPLOADED.value:
            enqueue_stage(r["id"], Stage.PARSE)
    if any(r["status"] == DocumentStatus.UPLOADED.value for r in results):
        ids = [uuid.UUID(r["id"]) for r in results]
        current = {str(d.id): d.status for d in session.execute(select(Document).where(Document.id.in_(ids))).scalars()}
        for r in results:
            r["status"] = current.get(r["id"], r["status"])
    return results


@router.get("/documents")
def list_documents(status: str | None = None, kind: str | None = None, q: str | None = None,
                   limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                   session: Session = Depends(get_session)) -> dict[str, Any]:
    stmt = select(Document)
    if status:
        stmt = stmt.where(Document.status.in_(status.split(",")))
    if kind:
        stmt = stmt.where(Document.kind == kind)
    if q:
        stmt = stmt.where(Document.filename.ilike(f"%{q}%"))
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = session.execute(stmt.order_by(Document.created_at.desc(), Document.id).limit(limit).offset(offset)).scalars().all()
    ids = [d.id for d in rows]
    inv_counts = dict(session.execute(select(Invoice.document_id, func.count()).where(Invoice.document_id.in_(ids)).group_by(Invoice.document_id)).all()) if ids else {}
    issue_counts = dict(session.execute(
        select(ValidationIssue.document_id, func.count()).where(ValidationIssue.document_id.in_(ids), ValidationIssue.severity == "error", ValidationIssue.resolved.is_(False)).group_by(ValidationIssue.document_id)
    ).all()) if ids else {}
    items = [{**doc_summary(d), "invoice_count": inv_counts.get(d.id, 0), "open_errors": issue_counts.get(d.id, 0)} for d in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    doc = _get_doc(session, doc_id)
    invoices = session.execute(select(Invoice).where(Invoice.document_id == doc.id).order_by(Invoice.page_start)).scalars().all()
    counts = dict(session.execute(
        select(ValidationIssue.invoice_id, func.count()).where(ValidationIssue.document_id == doc.id, ValidationIssue.severity == "error", ValidationIssue.resolved.is_(False)).group_by(ValidationIssue.invoice_id)
    ).all())
    ledger_count = session.execute(select(func.count()).where(LedgerEntry.document_id == doc.id)).scalar_one()
    methods = dict(session.execute(select(Page.method, func.count()).where(Page.document_id == doc.id).group_by(Page.method)).all())
    return {**doc_summary(doc),
            "invoices": [{**invoice_summary(i), "open_errors": counts.get(i.id, 0)} for i in invoices],
            "ledger_row_count": ledger_count, "page_methods": methods}


@router.get("/documents/{doc_id}/events")
def get_events(doc_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    doc = _get_doc(session, doc_id)
    rows = session.execute(select(ProcessingEvent).where(ProcessingEvent.document_id == doc.id).order_by(ProcessingEvent.created_at, ProcessingEvent.id)).scalars().all()
    items = [{"id": str(e.id), "stage": e.stage, "event": e.event, "error_code": e.error_code, "detail": e.detail,
              "duration_ms": e.duration_ms, "invoice_id": str(e.invoice_id) if e.invoice_id else None, "created_at": iso(e.created_at)} for e in rows]
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.get("/documents/{doc_id}/file")
def get_file(doc_id: str, session: Session = Depends(get_session)) -> FileResponse:
    doc = _get_doc(session, doc_id)
    if doc.storage_key.startswith("rejected-"):
        raise ApiError(404, ErrorCode.NOT_FOUND, "this file was rejected at upload and was not stored")
    path = LocalStorage(get_settings().storage_dir)._path(doc.storage_key)
    if not path.is_file():
        raise ApiError(404, ErrorCode.NOT_FOUND, "stored file is missing")
    return FileResponse(path, media_type=doc.mime, filename=doc.filename)


@router.get("/documents/{doc_id}/pages")
def get_pages(doc_id: str, start: int = Query(1, ge=1), end: int | None = Query(None, ge=1),
              session: Session = Depends(get_session)) -> dict[str, Any]:
    doc = _get_doc(session, doc_id)
    end = min(end or start + 9, start + 49)
    rows = session.execute(select(Page).where(Page.document_id == doc.id, Page.page_no >= start, Page.page_no <= end).order_by(Page.page_no)).scalars().all()
    items = [{"page_no": p.page_no, "method": p.method, "ocr_confidence": float(p.ocr_confidence) if p.ocr_confidence is not None else None,
              "text": p.text, "width": p.width, "height": p.height} for p in rows]
    return {"items": items, "total": doc.page_count or 0, "limit": end - start + 1, "offset": start - 1}


@router.get("/documents/{doc_id}/ledger")
def get_ledger(doc_id: str, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    doc = _get_doc(session, doc_id)
    base = select(LedgerEntry).where(LedgerEntry.document_id == doc.id)
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = session.execute(base.order_by(LedgerEntry.sheet_name, LedgerEntry.row_no).limit(limit).offset(offset)).scalars().all()
    items = [{"id": str(r.id), "sheet_name": r.sheet_name, "row_no": r.row_no, "invoice_number": r.invoice_number,
              "invoice_date": r.invoice_date, "supplier_name": r.supplier_name, "customer_name": r.customer_name,
              "subtotal": money(r.subtotal), "tax": money(r.tax), "total": money(r.total), "currency": r.currency} for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


_IN_FLIGHT = {DocumentStatus.UPLOADED.value, DocumentStatus.PARSING.value, DocumentStatus.EXTRACTING.value,
              DocumentStatus.VALIDATING.value, DocumentStatus.INDEXING.value}


@router.post("/documents/{doc_id}/reprocess", status_code=202)
def reprocess(doc_id: str, from_: str | None = Query(None, alias="from"), session: Session = Depends(get_session)) -> dict[str, Any]:
    doc = _get_doc(session, doc_id)
    if doc.storage_key.startswith("rejected-"):
        raise ApiError(400, ErrorCode.BAD_REQUEST, "this file was rejected at upload; please upload a fixed file instead")
    if from_ is not None:
        try:
            stage = Stage(from_)
        except ValueError:
            raise ApiError(400, ErrorCode.BAD_REQUEST, "from must be one of parse, extract, validate, index") from None
    elif doc.status == DocumentStatus.FAILED.value and doc.current_stage:
        stage = Stage(doc.current_stage)
    else:
        stage = Stage.PARSE
    if doc.status in _IN_FLIGHT and doc.status != DocumentStatus.UPLOADED.value and from_ is None:
        raise ApiError(409, ErrorCode.BAD_REQUEST, "document is still being processed")
    event(session, doc.id, stage.value, ProcessingEventType.RETRIED, detail={"reason": "reprocess requested"})
    doc.status = DocumentStatus.UPLOADED.value
    doc.error_code = doc.error_message = None
    session.commit()
    enqueue_stage(str(doc.id), stage)
    session.refresh(doc)
    return {**doc_summary(doc), "reprocess_from": stage.value}
