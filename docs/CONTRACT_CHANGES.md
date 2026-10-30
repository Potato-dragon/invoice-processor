# Contract changes

`docs/CONTRACTS.md` stays frozen. These are additions or clarifications made during integration (30 Oct 2026). None of them changes an existing shape.

| # | What | Why |
|---|---|---|
| 1 | **New endpoints:** `GET /api/documents/{id}/pages?start&end` (page text), `GET /api/documents/{id}/ledger` (spreadsheet rows), `GET /api/issues` (review queue, filters `severity, code, resolved, document_id`), `POST /api/issues/{id}/resolve` (`{"resolved": true}`). | The UI needs to show extracted text and ledger rows, and to let a reviewer mark a false alarm (e.g. a legitimate re-send) as checked. |
| 2 | **Rejected uploads are stored** as `documents` rows with `status=FAILED`, the error code, and `storage_key = "rejected-<uuid>"` (no file kept). | Failures must be visible and countable (`/stats` failure rate), not just returned once. |
| 3 | `POST /api/crosschecks/run` runs inline and returns `202` **with** the results (`summary`, `items`, `unmatched_right`). `left_ids` = invoice ids (empty = all). `right_ids` = invoice ids for PDF_PDF, or spreadsheet *document* ids for PDF_EXCEL (empty = all). | The dict-indexed match takes well under a second for thousands of rows, so a background job adds nothing. |
| 4 | `validate_invoice(extraction, pages, existing)` accepts either the `contracts.DuplicateLookup` model or any object with `find_candidates(...)` (`validation.lookup.DuplicateLookup` protocol, with `DbDuplicateLookup` / `InMemoryDuplicateLookup`). | The DB lookup must use indexes and exclude the invoice itself; a static list cannot. |
| 5 | Invalid dates such as `2026-02-30` are kept as the printed `YYYY-MM-DD` string in `invoice_date`, so validation can raise `INVALID_DATE`, instead of being nulled. | Nulling would hide the real problem behind `MISSING_FIELD`. |
| 6 | OCR page text may contain **tab characters** between cells on one visual row. | Keeps a label and its value on the same row, and shows two-column headers ("From: \| Client:") as separate cells. Grounding normalises whitespace, so evidence checks are unaffected. |
| 7 | Spreadsheet labels carry `ledger_rows` and `crosscheck_expected`; multi-invoice labels carry `invoices` (with page ranges) and `page_count`. | Needed for honest evaluation of spreadsheets, cross-checks and segmentation. |
| 8 | **New extraction method `llm_vision`** (enum `ExtractionMethod.LLM_VISION`). Notes may contain `VISION_UNVERIFIED:<field>`. | The LLM now reads the page image when OCR text is poor. A vision value that cannot be confirmed in the OCR text gets confidence 0.55 and this note, so validation raises `LOW_CONFIDENCE` and a person checks it. |
| 9 | Text-layer page text is rebuilt in **visual row order** (tab between cells), like OCR text (change 6). | Real PDFs often store a value before its label in the text stream. |
| 10 | Real-world evaluation sets: `data/public/` (invoice2data samples, MIT) and `data/real/` (private, git-ignored), each with its own `manifest.csv`, `samples/`, `labels/`. Run with `run_eval --root public` or `--root real`. | Synthetic results alone overstated real-world accuracy. |
