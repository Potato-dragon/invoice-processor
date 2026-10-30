"""Shared, lightweight contracts for every invoice-pipeline lane.

This module intentionally imports only the standard library and Pydantic so
workers can use its data shapes without pulling in database or OCR packages.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrEnum(str, Enum):
    """String enum compatible with database/API values on Python 3.12."""


class DocumentKind(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    SPREADSHEET = "spreadsheet"


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    AUTO_OK = "AUTO_OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    CORRECTED = "CORRECTED"


class Stage(StrEnum):
    PARSE = "parse"
    EXTRACT = "extract"
    VALIDATE = "validate"
    INDEX = "index"


class ProcessingEventType(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRIED = "RETRIED"
    SKIPPED = "SKIPPED"


class PageMethod(StrEnum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    NONE = "none"


class ExtractionMethod(StrEnum):
    RULES = "rules"
    LLM_PRIMARY = "llm_primary"
    LLM_FALLBACK = "llm_fallback"
    LLM_VISION = "llm_vision"  # LLM read the page image (see CONTRACT_CHANGES 8)
    MANUAL = "manual"


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ErrorCode(StrEnum):
    FILE_TYPE_UNSUPPORTED = "FILE_TYPE_UNSUPPORTED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_CORRUPT = "FILE_CORRUPT"
    FILE_ENCRYPTED = "FILE_ENCRYPTED"
    PAGE_LIMIT_EXCEEDED = "PAGE_LIMIT_EXCEEDED"
    FILE_EMPTY = "FILE_EMPTY"
    OCR_FAILED = "OCR_FAILED"
    SPREADSHEET_PARSE_FAILED = "SPREADSHEET_PARSE_FAILED"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_INVALID_OUTPUT = "LLM_INVALID_OUTPUT"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    STORAGE_ERROR = "STORAGE_ERROR"
    NOT_FOUND = "NOT_FOUND"
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class IssueCode(StrEnum):
    MISSING_FIELD = "MISSING_FIELD"
    LINE_ITEMS_SUBTOTAL_MISMATCH = "LINE_ITEMS_SUBTOTAL_MISMATCH"
    SUBTOTAL_TAX_TOTAL_MISMATCH = "SUBTOTAL_TAX_TOTAL_MISMATCH"
    NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"
    INVALID_DATE = "INVALID_DATE"
    DUPLICATE_EXACT = "DUPLICATE_EXACT"
    DUPLICATE_FUZZY = "DUPLICATE_FUZZY"
    CURRENCY_AMBIGUOUS = "CURRENCY_AMBIGUOUS"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    LOW_OCR_CONFIDENCE = "LOW_OCR_CONFIDENCE"
    CROSS_PDF_MISMATCH = "CROSS_PDF_MISMATCH"
    CROSS_EXCEL_MISMATCH = "CROSS_EXCEL_MISMATCH"
    CROSS_NO_MATCH = "CROSS_NO_MATCH"


class PipelineError(Exception):
    """Expected, coded pipeline failure that should not be retried blindly."""

    def __init__(self, code: ErrorCode | str, message: str) -> None:
        self.code = ErrorCode(code)
        self.message = message
        super().__init__(f"{self.code.value}: {message}")


class ParsedPage(BaseModel):
    page_no: int = Field(ge=1)
    text: str = ""
    method: PageMethod
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)


class LedgerRow(BaseModel):
    sheet_name: str
    row_no: int = Field(ge=1)
    invoice_number: str | None = None
    invoice_date: str | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    subtotal: str | None = None
    tax: str | None = None
    total: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    raw: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    pages: list[ParsedPage] = Field(default_factory=list)
    invoice_ranges: list[tuple[int, int]] = Field(default_factory=list)
    ledger_rows: list[LedgerRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExtractedField(BaseModel):
    value: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None
    page: int | None = Field(default=None, ge=1)

    @field_validator("evidence")
    @classmethod
    def evidence_for_value(cls, value: str | None, info: Any) -> str | None:
        if info.data.get("value") is not None and not value:
            raise ValueError("a non-null extraction value requires evidence")
        return value


class ExtractedLineItem(BaseModel):
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None
    page: int | None = Field(default=None, ge=1)


class ExtractionResult(BaseModel):
    """The central extraction JSON object defined by CONTRACTS section 7."""

    model_config = ConfigDict(use_enum_values=True)

    invoice_number: ExtractedField
    invoice_date: ExtractedField
    supplier_name: ExtractedField
    customer_name: ExtractedField
    subtotal: ExtractedField
    tax: ExtractedField
    total: ExtractedField
    currency: ExtractedField
    line_items: list[ExtractedLineItem] = Field(default_factory=list)
    method: ExtractionMethod
    notes: list[str] = Field(default_factory=list)


class IssueModel(BaseModel):
    code: IssueCode
    severity: IssueSeverity
    field: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    resolved: bool = False


class DuplicateLookup(BaseModel):
    """Candidate invoices supplied to validation for duplicate detection."""

    model_config = ConfigDict(extra="allow")
    exact_matches: list[dict[str, Any]] = Field(default_factory=list)
    fuzzy_matches: list[dict[str, Any]] = Field(default_factory=list)


class CrosscheckKind(StrEnum):
    PDF_PDF = "PDF_PDF"
    PDF_EXCEL = "PDF_EXCEL"


class CrosscheckOutcome(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NO_MATCH = "NO_MATCH"


class CrosscheckResult(BaseModel):
    kind: CrosscheckKind
    left_ref: dict[str, Any]
    right_ref: dict[str, Any]
    result: CrosscheckOutcome
    details: dict[str, Any] = Field(default_factory=dict)
