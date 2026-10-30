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
