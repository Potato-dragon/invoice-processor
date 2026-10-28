# CONTRACTS (FROZEN). Do not edit. Propose changes in docs/CONTRACT_CHANGES.md.

Everything here is the single source of truth for data shapes, so independently built lanes fit together.

## 1. Stack
Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Postgres 16 with pgvector, Redis + RQ (queue), Next.js (frontend), Pydantic v2. Backend and worker run in Docker (image includes tesseract-ocr, with English plus common languages as small packs). Local embeddings via `fastembed` (ONNX, 384 dims, e.g. bge-small), NOT PyTorch.

## 2. Config (environment variables)
`API_KEY`, `DATABASE_URL`, `REDIS_URL`, `STORAGE_DIR` (default `/data/storage`), `GEMINI_API_KEY`, `LLM_PRIMARY_MODEL` (default Gemma 4), `LLM_FALLBACK_MODEL` (default Gemini Flash-Lite), `LLM_FAKE` (true in tests), `MAX_UPLOAD_MB` (50), `MAX_PAGES` (1500), `OCR_DPI` (300). Provide `.env.example`.

## 3. Enumerations
- `documents.kind`: `pdf | image | spreadsheet`
- `documents.status`: `UPLOADED | PARSING | EXTRACTING | VALIDATING | INDEXING | COMPLETED | NEEDS_REVIEW | FAILED`
  - Document is `NEEDS_REVIEW` if any of its invoices needs review; `COMPLETED` otherwise.
- `invoices.review_status`: `PENDING | AUTO_OK | NEEDS_REVIEW | CORRECTED`
- Stages (queue names too): `parse | extract | validate | index`
- `processing_events.event`: `STARTED | SUCCEEDED | FAILED | RETRIED | SKIPPED`
- `page.method`: `text_layer | ocr | none`
- `extraction_method`: `rules | llm_primary | llm_fallback | manual`
- Issue severity: `error | warning | info`

## 4. Error codes (documents.error_code, event.error_code, API errors)
`FILE_TYPE_UNSUPPORTED, FILE_TOO_LARGE, FILE_CORRUPT, FILE_ENCRYPTED, PAGE_LIMIT_EXCEEDED, FILE_EMPTY, OCR_FAILED, SPREADSHEET_PARSE_FAILED, LLM_RATE_LIMITED, LLM_INVALID_OUTPUT, LLM_UNAVAILABLE, EXTRACTION_FAILED, VALIDATION_FAILED, STORAGE_ERROR, NOT_FOUND, BAD_REQUEST, UNAUTHORIZED, RATE_LIMITED, INTERNAL_ERROR`

API error body (always): `{"error": {"code": "<CODE>", "message": "<human text>"}}`

## 5. Validation issue codes
`MISSING_FIELD, LINE_ITEMS_SUBTOTAL_MISMATCH, SUBTOTAL_TAX_TOTAL_MISMATCH, NEGATIVE_AMOUNT, INVALID_DATE, DUPLICATE_EXACT, DUPLICATE_FUZZY, CURRENCY_AMBIGUOUS, EVIDENCE_NOT_FOUND, LOW_CONFIDENCE, LOW_OCR_CONFIDENCE, CROSS_PDF_MISMATCH, CROSS_EXCEL_MISMATCH, CROSS_NO_MATCH`
Tolerance for money comparisons: absolute 0.02 in the invoice currency unit. Duplicate rule: exact = same normalized supplier + invoice_number + total; fuzzy = same supplier (rapidfuzz >= 90) and (same invoice_number or same total + date within 3 days).

## 6. Database tables (Postgres)
All ids are UUID. `created_at`/`updated_at` are timestamptz. Money columns are `numeric(18,4)`.

- **documents**: id, filename, mime, size_bytes, sha256, storage_key, kind, status, current_stage, error_code, error_message, page_count, created_at, updated_at
- **pages**: id, document_id, page_no, text, method, ocr_confidence (0-1, nullable), width, height. Unique (document_id, page_no)
- **invoices**: id, document_id, page_start, page_end, review_status, extraction (jsonb, full object from section 7), invoice_number, invoice_date, supplier_name, customer_name, subtotal, tax, total, currency (char 3, nullable), extraction_method, fts (tsvector), embedding (vector(384)), created_at, updated_at
- **invoice_line_items**: id, invoice_id, line_no, description, quantity, unit_price, amount
- **validation_issues**: id, document_id, invoice_id (nullable), code, severity, field (nullable), message, details (jsonb), resolved (bool), created_at
- **processing_events**: id, document_id, invoice_id (nullable), stage, event, error_code (nullable), detail (jsonb), duration_ms, created_at
- **corrections**: id, invoice_id, field, old_value, new_value, created_at
- **ledger_entries**: id, document_id, sheet_name, row_no, invoice_number, invoice_date, supplier_name, customer_name, subtotal, tax, total, currency, raw (jsonb)
- **crosschecks**: id, kind (`PDF_PDF | PDF_EXCEL`), left_ref (jsonb), right_ref (jsonb), result (`MATCH | MISMATCH | NO_MATCH`), details (jsonb), created_at
- **llm_cache**: key (sha256 text, pk), model, response (jsonb), created_at

Indexes: documents(status), documents(sha256), invoices(supplier_name), invoices(invoice_number), invoices(invoice_date), GIN on invoices.fts, HNSW or IVFFlat on invoices.embedding.

## 7. Extraction object (the central JSON shape)
```json
{
  "invoice_number": {"value": "INV-001", "confidence": 0.97, "evidence": "Invoice No: INV-001", "page": 1},
  "invoice_date":   {"value": "2026-03-14", "confidence": 0.9, "evidence": "...", "page": 1},
  "supplier_name":  {"value": null, "confidence": 0.0, "evidence": null, "page": null},
  "customer_name":  {...}, "subtotal": {...}, "tax": {...}, "total": {...},
  "currency":       {"value": "USD", "confidence": 0.8, "evidence": "...", "page": 1},
  "line_items": [
    {"description": "...", "quantity": "2", "unit_price": "10.00", "amount": "20.00",
     "confidence": 0.9, "evidence": "...", "page": 1}
  ],
  "method": "rules",
  "notes": []
}
```
Rules: money/quantity are decimal STRINGS (never floats), dates ISO `YYYY-MM-DD`, currency ISO 4217 or null. A field not found has `value: null`, confidence 0. A non-null value MUST have evidence text that appears in the page text (after whitespace normalization), otherwise it is nulled and an `EVIDENCE_NOT_FOUND` issue is raised. Ambiguous symbols (a bare "$") leave currency null plus `CURRENCY_AMBIGUOUS`. Numbers like `1.234,56` and `1,234.56` must both parse correctly.

## 8. Module interfaces (so lanes plug together)
Each lane exports these functions from its package. All take/return Pydantic models defined in `backend/app/contracts.py` (Lane A creates that file from this document).

- `parsing.parse_document(file_path: str, kind: str) -> ParsedDocument`
  - `ParsedDocument`: `pages: list[ParsedPage]`, `invoice_ranges: list[(page_start, page_end)]`, `ledger_rows: list[LedgerRow]`, `warnings: list[str]`
  - `ParsedPage`: `page_no, text, method, ocr_confidence, width, height`
  - Raises `PipelineError(code, message)` using codes from section 4.
- `extraction.extract_invoice(pages: list[ParsedPage]) -> ExtractionResult` (the section 7 object plus `method`)
- `validation.validate_invoice(extraction: ExtractionResult, pages, existing: DuplicateLookup) -> list[IssueModel]`
- `validation.crosscheck(left, right) -> CrosscheckResult`
- `PipelineError` and the models live in `contracts.py`. Stage runners in lane A call these functions; until a lane lands, lane A provides stub versions in `backend/app/stubs/`.

## 9. REST API (all under `/api`, header `X-API-Key` required except health)
| Method + path | Purpose | Notes |
|---|---|---|
| GET `/health` | liveness | no auth |
| POST `/documents` | upload one or many files (multipart field `files`) | returns `[{id, filename, status, error?}]`; per-file errors do not fail the batch |
| GET `/documents` | list | query: `status, kind, q, limit, offset` |
| GET `/documents/{id}` | detail incl. status, stage, error, page_count, invoice summaries | |
| GET `/documents/{id}/events` | processing history | |
| GET `/documents/{id}/file` | download original | |
| POST `/documents/{id}/reprocess` | re-run from failed stage (or `?from=parse`) | 202 |
| GET `/invoices/{id}` | full invoice incl. extraction, line items, issues, page range | |
| PATCH `/invoices/{id}` | manual correction: `{field: new_value, ...}` | writes `corrections`, sets CORRECTED, re-runs validation |
| GET `/search` | `q, mode=keyword|semantic|hybrid, supplier, currency, date_from, date_to, min_total, max_total, review_status, limit, offset` | returns invoices with score |
| POST `/crosschecks/run` | `{kind, left_ids, right_ids}` | 202 |
| GET `/crosschecks` | list results | |
| GET `/stats` | counts by status/error_code, avg processing time | used by eval |

Pagination shape: `{"items": [...], "total": N, "limit": N, "offset": N}`.

## 10. Test data and ground truth (Lane F)
- Every sample file `data/samples/<id>.<ext>` has `data/labels/<id>.json` containing the section 7 object with `value` fields only (ground truth; nulls where the truth is absent), plus `"invoice_count"` for multi-invoice files.
- `data/manifest.csv` columns: `id, filename, kind, layout, supplier, locale, currency, quality, split (dev|test), expected_status (COMPLETED|NEEDS_REVIEW|FAILED), expected_error_code, notes`.
- Split by layout and supplier, never randomly: test layouts/suppliers do not appear in dev.
