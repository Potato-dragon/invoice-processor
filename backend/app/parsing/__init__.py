"""Parsing: PDF text layer / OCR, images, spreadsheets, invoice segmenter.

Public API (CONTRACTS section 8):
    parse_document(file_path, kind) -> ParsedDocument
"""
from __future__ import annotations

from app.contracts import DocumentKind, ErrorCode, ParsedDocument, PipelineError
from app.parsing.images import parse_image_pages
from app.parsing.pdf import parse_pdf_pages
from app.parsing.segment import segment_pages
from app.parsing.spreadsheets import parse_spreadsheet_rows


def parse_document(file_path: str, kind: str) -> ParsedDocument:
    warnings: list[str] = []
    kind = DocumentKind(kind).value if kind in {k.value for k in DocumentKind} else kind
    if kind == DocumentKind.PDF:
        pages = parse_pdf_pages(file_path, warnings)
        return ParsedDocument(pages=pages, invoice_ranges=segment_pages(pages), warnings=warnings)
    if kind == DocumentKind.IMAGE:
        pages = parse_image_pages(file_path, warnings)
        # A multi-frame TIFF can hold several invoices, like a PDF.
        return ParsedDocument(pages=pages, invoice_ranges=segment_pages(pages), warnings=warnings)
    if kind == DocumentKind.SPREADSHEET:
        rows = parse_spreadsheet_rows(file_path, warnings)
        return ParsedDocument(ledger_rows=rows, warnings=warnings)
    raise PipelineError(ErrorCode.FILE_TYPE_UNSUPPORTED, f"unknown document kind: {kind}")


__all__ = ["parse_document", "segment_pages"]
