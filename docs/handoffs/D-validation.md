# Handoff D: Validation, duplicates and cross-checks

**Branch:** `lane-d/validation`
**You own:** `backend/app/validation/`, `backend/tests/validation/`.
**Allowed outside your folder:** append-only lines to `backend/requirements.txt` under a `# validation` comment (rapidfuzz is expected). You may import `app.db` / `app.models` (read-only) for the duplicate lookup.
**Do not touch:** other `backend/app/` folders, `frontend/`, `tools/`, `data/`, `docs/CONTRACTS.md`, `docker-compose.yml`.
**Read first:** AGENTS.md, DECISIONS.md (items 10 and 11), docs/ARCHITECTURE.md, docs/CONTRACTS.md (sections 5, 6, 7, 8), `backend/app/contracts.py`.

## Goal
Implement `validation.validate_invoice(extraction, pages, existing) -> list[IssueModel]` and `validation.crosscheck(left, right) -> CrosscheckResult` as in CONTRACTS section 8. All math uses `Decimal`. Pure functions where possible; deterministic; no LLM, no network.

## Shared conventions (same in lanes B, C, D)
- Field names: invoice_number, invoice_date, supplier_name, customer_name, subtotal, tax, total, currency, line_items.
- Receipts are invoice-like documents (DECISIONS 10).
- Lane C puts these tokens in `extraction.notes`: `CURRENCY_AMBIGUOUS` and `EVIDENCE_NOT_FOUND:<field>`. You convert them to issues.
- Money tolerance: absolute 0.02 in the invoice currency unit (CONTRACTS section 5).
- Do not run `docker compose build/up` yourself; write code, then list the commands for the human to run. Don't re-read files you already read. If a command fails twice, stop and report.

## Severity rules (DECISIONS 11)
- `error`: missing invoice_number, invoice_date, supplier_name or total (`MISSING_FIELD`); `CURRENCY_AMBIGUOUS`; both arithmetic mismatch codes; `NEGATIVE_AMOUNT`; `INVALID_DATE` (unparseable or impossible); `DUPLICATE_EXACT`; `DUPLICATE_FUZZY`; `CROSS_PDF_MISMATCH`; `CROSS_EXCEL_MISMATCH`; `CROSS_NO_MATCH`.
- `info`: missing customer_name or tax (`MISSING_FIELD`).
- `warning`: `LOW_CONFIDENCE` (a non-null field below 0.6), `LOW_OCR_CONFIDENCE` (page ocr_confidence below 0.6), `EVIDENCE_NOT_FOUND`, implausible date (before 2000 or more than 1 year in the future, code `INVALID_DATE`).
- Any `error` issue means the invoice is NEEDS_REVIEW (lane A applies that; you only return issues).
Each issue sets `code`, `severity`, `field`, a short human message in plain words, and `details` (the numbers involved).

## Tasks
1. **Field checks**: MISSING_FIELD per the table above. If tax is null but subtotal equals total, that is fine (no tax). If a check needs a missing input, skip it quietly (do not raise extra errors).
2. **Arithmetic**: sum of line item amounts vs subtotal (`LINE_ITEMS_SUBTOTAL_MISMATCH`); subtotal + tax vs total (`SUBTOTAL_TAX_TOTAL_MISMATCH`); per line, quantity x unit_price vs amount (code `LINE_ITEMS_SUBTOTAL_MISMATCH`, field `line_items[i]`, severity `warning`). Rounding drift within 0.02 is fine.
3. **Sanity**: `NEGATIVE_AMOUNT` for any negative subtotal, tax, total or line amount; `INVALID_DATE` per the rules above.
4. **Quality issues**: `LOW_CONFIDENCE`, `LOW_OCR_CONFIDENCE` (use the pages of the invoice), `CURRENCY_AMBIGUOUS` and `EVIDENCE_NOT_FOUND` from notes.
5. **Duplicates**: define a `DuplicateLookup` Protocol in `validation/lookup.py` (if `contracts.py` already has one, use that) with `find_candidates(supplier_name, invoice_number, total, invoice_date) -> list[ExistingInvoice]`. Provide `DbDuplicateLookup(session, exclude_invoice_id)` that queries the `invoices` table using its indexes and never returns the invoice being validated, and an in-memory implementation for tests. Rules from CONTRACTS section 5: exact = same normalized supplier + invoice_number + total (`DUPLICATE_EXACT`); fuzzy = same supplier (rapidfuzz ratio 90 or more) and (same invoice_number, or same total with dates within 3 days) (`DUPLICATE_FUZZY`). Normalize supplier names: lowercase, strip punctuation and legal suffixes (Ltd, Inc, LLC, GmbH, SA, SpA, Oy, ...). Put the matching invoice ids in `details`.
6. **Cross-checks**: `crosscheck(left, right)` returns MATCH, MISMATCH or NO_MATCH with field-by-field differences in `details`. PDF vs PDF: match on exact key (normalized invoice_number + normalized supplier), then compare total, subtotal, tax, date, currency with tolerance. PDF vs Excel: left is an invoice, right is a list of ledger rows; match the same way, compare the same fields. Add `crosscheck_batch(kind, left_items, right_items)` using a dict index (must handle thousands of rows in well under a second, no O(n^2)) that also reports unmatched ledger rows. Add `crosscheck_issues(result) -> list[IssueModel]` mapping to the three CROSS_* codes. Exact keys only, no fuzzy matching here.
7. **Tests** in `backend/tests/validation/`: one test per rule and edge case (rounding, missing tax, negative, date formats, near-duplicate with a typo, duplicate excluding itself, ledger row missing, differing totals), plus a performance test on 5,000 ledger rows. Add integration tests against `data/labels/*.json` and `data/manifest.csv` only if they exist: every seeded error in the manifest (`expected_status = NEEDS_REVIEW`) must produce at least one error issue, and clean `COMPLETED` documents must produce none.

## Acceptance checks
- `docker compose exec api python -m pytest tests/validation` passes.
- Report the measured recall on seeded errors and the false-positive rate on clean documents (targets: 100% recall, under 5% false positives), if lane F's data exists.
- All amounts are `Decimal`; no float anywhere in the package.
- Issue messages are plain-language and do not blame anyone.

## Out of scope
Parsing, extraction, database schema changes, API, frontend, deciding document status (lane A does that from your issues).
