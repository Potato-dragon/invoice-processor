# Handoff B: Parsing (PDF text, OCR, images, spreadsheets, invoice segmenter)

**Branch:** `lane-b/parsing`
**You own:** `backend/app/parsing/`, `backend/tests/parsing/`.
**Allowed outside your folder:** append-only lines to `backend/requirements.txt` under a `# parsing` comment. Nothing else.
**Do not touch:** other `backend/app/` folders, `frontend/`, `tools/`, `data/`, `docs/CONTRACTS.md`, `docker-compose.yml`.
**Read first:** AGENTS.md, DECISIONS.md, docs/ARCHITECTURE.md, docs/CONTRACTS.md (sections 3, 4, 7, 8), `backend/app/contracts.py`.

## Goal
Implement `parsing.parse_document(file_path: str, kind: str) -> ParsedDocument` exactly as in CONTRACTS section 8. It must be fast and memory-safe on a 1,000-page PDF, and every failure must raise `PipelineError(code, message)` with a code from CONTRACTS section 4. No LLM, no database writes, no API code (lane A's stage runner calls you and stores the result).

## Shared conventions (same in lanes B, C, D)
- Field names: invoice_number, invoice_date, supplier_name, customer_name, subtotal, tax, total, currency, line_items.
- Receipts are invoice-like documents (DECISIONS 10). Page text must be returned as-is; do not strip labels.
- Money is `Decimal`/string, never float. Dates ISO `YYYY-MM-DD`.
- Do not run `docker compose build/up` yourself; write code, then list the exact commands for the human to run. Don't re-read files you already read. If a command fails twice, stop and report.

## Tasks
1. **PDF reading** (PyMuPDF). Check `MAX_PAGES` first (`PAGE_LIMIT_EXCEEDED`), encrypted -> `FILE_ENCRYPTED`, unreadable/truncated -> `FILE_CORRUPT`, zero pages -> `FILE_EMPTY`. Per page: if the text layer has at least 25 non-space characters use it (`method=text_layer`, `ocr_confidence=None`), otherwise OCR it. Fill `width`/`height`. Pages with nothing recoverable get `method=none`, empty text, plus a warning.
2. **OCR** (Tesseract + OpenCV). Render at `OCR_DPI` page by page (never hold all page images in memory). Cleanup: grayscale, deskew (small angles up to about 10 degrees), denoise, adaptive threshold only if it helps contrast. Call Tesseract with a 60 s timeout per page. `ocr_confidence` = mean word confidence from Tesseract TSV scaled to 0-1 (0.0 if no words). One page failing OCR must not fail the document: mark it `method=none` with a warning. If every page fails, raise `OCR_FAILED`. Use a small worker pool (max 4) for OCR pages.
3. **Images**: JPG, PNG, TIFF (multi-frame TIFF = one page per frame) via Pillow. Respect EXIF rotation, convert modes safely, keep Pillow's decompression-bomb guard on. Corrupt image -> `FILE_CORRUPT`.
4. **Spreadsheets**: XLSX (openpyxl), legacy XLS (xlrd), CSV (csv module). CSV: sniff delimiter (`,` `;` tab `|`), try utf-8-sig then utf-8 then latin-1. Read ALL sheets, skip empty or junk sheets, find the header row (not always row 1) by scoring rows for known header words, map columns to `LedgerRow` fields using a synonym table (English plus French, German, Spanish basics: "Invoice No", "Bill #", "Facture", "Rechnung", "Supplier", "Vendor", "Total", "Amount", ...). Parse money to decimal strings with a locale-safe parser that handles `1,234.56`, `1.234,56`, `1 234,56`, `1,23,456.78`, currency symbols, parentheses negatives. Keep the original row in `raw`. Spreadsheets return `pages=[]` and `invoice_ranges=[]`. Nothing parseable or corrupt file -> `SPREADSHEET_PARSE_FAILED`.
5. **Segmenter** (rules only, no LLM): split a multi-invoice PDF into `invoice_ranges` (1-based inclusive page ranges, ordered, covering every page with no gaps or overlaps). Signals: a new invoice-number value (labels like Invoice No, Invoice #, Bill #, Facture, Rechnung, Receipt No), "Page 1 of N" resets, and a header block that differs from the previous page. A page with "Page k of N", k > 1, belongs to the previous invoice. Fall back to one range per document when no signal is found. Segmenting 1,000 pages must take only a few seconds.
6. **Tests** in `backend/tests/parsing/`. Build tiny fixtures in code (PyMuPDF, Pillow, openpyxl), do not depend on `data/`. Cover: text-layer PDF, scanned PDF, rotated/noisy scan, multi-frame TIFF, XLSX with junk sheet and header on row 5, semicolon latin-1 CSV, XLS, corrupt PDF, encrypted PDF, empty file, page limit, segmenter on a synthetic 8-invoice PDF. Add integration tests that run against `data/samples/` and `data/labels/` only if those files exist (skip otherwise).

## Acceptance checks
- `docker compose exec api python -m pytest tests/parsing` passes.
- Failure files raise exactly: corrupt -> FILE_CORRUPT, encrypted -> FILE_ENCRYPTED, empty -> FILE_EMPTY, over limit -> PAGE_LIMIT_EXCEEDED, bad spreadsheet -> SPREADSHEET_PARSE_FAILED.
- A synthetic 100-page digital PDF parses in under 10 s. Report measured pages/second for text-layer and for OCR.
- Segmenter finds all 8 invoices in the synthetic fixture. If the 30-page sample from lane F exists, report boundary precision/recall against its label file (target 95%+).
- Peak memory stays flat while parsing a 1,000-page PDF (render and discard page by page).
- No dependency over about 100 MB, no model downloads.

## Out of scope
Extraction, validation, database, API, frontend.
