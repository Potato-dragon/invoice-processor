"""Database schema models. Canonical schema changes live in Alembic."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db import Base


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimensions})"


def id_column() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_status", "status"), Index("ix_documents_sha256", "sha256"))
    id: Mapped[uuid.UUID] = id_column()
    filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_no", name="uq_pages_document_page"),)
    id: Mapped[uuid.UUID] = id_column()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_supplier_name", "supplier_name"), Index("ix_invoices_invoice_number", "invoice_number"),
        Index("ix_invoices_invoice_date", "invoice_date"), Index("ix_invoices_fts", "fts", postgresql_using="gin"),
        Index("ix_invoices_embedding", "embedding", postgresql_using="hnsw", postgresql_ops={"embedding": "vector_l2_ops"}),
    )
    id: Mapped[uuid.UUID] = id_column()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    invoice_number: Mapped[str | None] = mapped_column(String(255))
    invoice_date: Mapped[str | None] = mapped_column(String(10))
    supplier_name: Mapped[str | None] = mapped_column(String(512))
    customer_name: Mapped[str | None] = mapped_column(String(512))
    subtotal: Mapped[Any | None] = mapped_column(Numeric(18, 4))
    tax: Mapped[Any | None] = mapped_column(Numeric(18, 4))
    total: Mapped[Any | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    extraction_method: Mapped[str | None] = mapped_column(String(32))
    fts: Mapped[str | None] = mapped_column(TSVECTOR)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"
    __table_args__ = (UniqueConstraint("invoice_id", "line_no", name="uq_line_items_invoice_line"),)
    id: Mapped[uuid.UUID] = id_column()
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Any | None] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Any | None] = mapped_column(Numeric(18, 4))
    amount: Mapped[Any | None] = mapped_column(Numeric(18, 4))


class ValidationIssue(Base):
    __tablename__ = "validation_issues"
    id: Mapped[uuid.UUID] = id_column()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    field: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProcessingEvent(Base):
    __tablename__ = "processing_events"
    id: Mapped[uuid.UUID] = id_column()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Correction(Base):
    __tablename__ = "corrections"
    id: Mapped[uuid.UUID] = id_column()
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    field: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[uuid.UUID] = id_column()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_number: Mapped[str | None] = mapped_column(String(255))
    invoice_date: Mapped[str | None] = mapped_column(String(10))
    supplier_name: Mapped[str | None] = mapped_column(String(512))
    customer_name: Mapped[str | None] = mapped_column(String(512))
    subtotal: Mapped[Any | None] = mapped_column(Numeric(18, 4))
    tax: Mapped[Any | None] = mapped_column(Numeric(18, 4))
    total: Mapped[Any | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Crosscheck(Base):
    __tablename__ = "crosschecks"
    id: Mapped[uuid.UUID] = id_column()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    left_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    right_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LlmCache(Base):
    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
