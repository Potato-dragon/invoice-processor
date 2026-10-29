"""create invoice schema

Revision ID: 0001_initial_schema
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "vector(384)"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("documents", sa.Column("id", UUID, primary_key=True), sa.Column("filename", sa.String(1024), nullable=False), sa.Column("mime", sa.String(255), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False), sa.Column("storage_key", sa.String(255), nullable=False, unique=True), sa.Column("kind", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("current_stage", sa.String(32)), sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text()), sa.Column("page_count", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_table("pages", sa.Column("id", UUID, primary_key=True), sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False), sa.Column("page_no", sa.Integer(), nullable=False), sa.Column("text", sa.Text(), nullable=False), sa.Column("method", sa.String(32), nullable=False), sa.Column("ocr_confidence", sa.Numeric(4, 3)), sa.Column("width", sa.Integer()), sa.Column("height", sa.Integer()), sa.UniqueConstraint("document_id", "page_no", name="uq_pages_document_page"))
    op.create_table("invoices", sa.Column("id", UUID, primary_key=True), sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False), sa.Column("page_start", sa.Integer(), nullable=False), sa.Column("page_end", sa.Integer(), nullable=False), sa.Column("review_status", sa.String(32), nullable=False), sa.Column("extraction", JSONB, nullable=False), sa.Column("invoice_number", sa.String(255)), sa.Column("invoice_date", sa.String(10)), sa.Column("supplier_name", sa.String(512)), sa.Column("customer_name", sa.String(512)), sa.Column("subtotal", sa.Numeric(18, 4)), sa.Column("tax", sa.Numeric(18, 4)), sa.Column("total", sa.Numeric(18, 4)), sa.Column("currency", sa.String(3)), sa.Column("extraction_method", sa.String(32)), sa.Column("fts", postgresql.TSVECTOR()), sa.Column("embedding", Vector()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_index("ix_invoices_supplier_name", "invoices", ["supplier_name"])
    op.create_index("ix_invoices_invoice_number", "invoices", ["invoice_number"])
    op.create_index("ix_invoices_invoice_date", "invoices", ["invoice_date"])
    op.create_index("ix_invoices_fts", "invoices", ["fts"], postgresql_using="gin")
    op.execute("CREATE INDEX ix_invoices_embedding ON invoices USING hnsw (embedding vector_l2_ops)")
    op.create_table("invoice_line_items", sa.Column("id", UUID, primary_key=True), sa.Column("invoice_id", UUID, sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False), sa.Column("line_no", sa.Integer(), nullable=False), sa.Column("description", sa.Text()), sa.Column("quantity", sa.Numeric(18, 4)), sa.Column("unit_price", sa.Numeric(18, 4)), sa.Column("amount", sa.Numeric(18, 4)), sa.UniqueConstraint("invoice_id", "line_no", name="uq_line_items_invoice_line"))
    op.create_table("validation_issues", sa.Column("id", UUID, primary_key=True), sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False), sa.Column("invoice_id", UUID, sa.ForeignKey("invoices.id", ondelete="CASCADE")), sa.Column("code", sa.String(64), nullable=False), sa.Column("severity", sa.String(16), nullable=False), sa.Column("field", sa.String(128)), sa.Column("message", sa.Text(), nullable=False), sa.Column("details", JSONB, nullable=False), sa.Column("resolved", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("processing_events", sa.Column("id", UUID, primary_key=True), sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False), sa.Column("invoice_id", UUID, sa.ForeignKey("invoices.id", ondelete="CASCADE")), sa.Column("stage", sa.String(32), nullable=False), sa.Column("event", sa.String(16), nullable=False), sa.Column("error_code", sa.String(64)), sa.Column("detail", JSONB, nullable=False), sa.Column("duration_ms", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("corrections", sa.Column("id", UUID, primary_key=True), sa.Column("invoice_id", UUID, sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False), sa.Column("field", sa.String(128), nullable=False), sa.Column("old_value", sa.Text()), sa.Column("new_value", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("ledger_entries", sa.Column("id", UUID, primary_key=True), sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False), sa.Column("sheet_name", sa.String(255), nullable=False), sa.Column("row_no", sa.Integer(), nullable=False), sa.Column("invoice_number", sa.String(255)), sa.Column("invoice_date", sa.String(10)), sa.Column("supplier_name", sa.String(512)), sa.Column("customer_name", sa.String(512)), sa.Column("subtotal", sa.Numeric(18, 4)), sa.Column("tax", sa.Numeric(18, 4)), sa.Column("total", sa.Numeric(18, 4)), sa.Column("currency", sa.String(3)), sa.Column("raw", JSONB, nullable=False))
    op.create_table("crosschecks", sa.Column("id", UUID, primary_key=True), sa.Column("kind", sa.String(16), nullable=False), sa.Column("left_ref", JSONB, nullable=False), sa.Column("right_ref", JSONB, nullable=False), sa.Column("result", sa.String(16), nullable=False), sa.Column("details", JSONB, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("llm_cache", sa.Column("key", sa.String(64), primary_key=True), sa.Column("model", sa.String(255), nullable=False), sa.Column("response", JSONB, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))


def downgrade() -> None:
    op.drop_table("llm_cache"); op.drop_table("crosschecks"); op.drop_table("ledger_entries"); op.drop_table("corrections"); op.drop_table("processing_events"); op.drop_table("validation_issues"); op.drop_table("invoice_line_items")
    op.execute("DROP INDEX IF EXISTS ix_invoices_embedding")
    op.drop_table("invoices"); op.drop_table("pages"); op.drop_table("documents")
