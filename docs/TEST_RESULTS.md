# Test results

Run on 30 Oct 2026 inside the `api` container (`docker compose exec api python -m pytest -q`) against a separate `invoice_test` database, with `LLM_FAKE=true` and the pipeline running inline.

**143 passed, 0 failed** (backend), plus 5 passed (data generator).

| Suite | Tests | What it covers |
|---|---|---|
| `tests/parsing` | 27 | Text-layer PDF; scanned PDF via OCR; rotated, noisy and blurred scan (deskew); skew estimate at −6/−3/3/5°; PNG/JPG; multi-frame TIFF; corrupt PDF, text renamed to .pdf, encrypted PDF, empty files, page limit, blank PDF → `OCR_FAILED`; 100-page PDF in under 10 s; XLSX with a junk sheet and header on row 5; semicolon latin-1 CSV with European numbers; tab and pipe CSV; legacy XLS; spreadsheets stored without an extension; corrupt XLSX and table-less CSV → `SPREADSHEET_PARSE_FAILED`; segmenter on an 8-invoice PDF, by number change, full page coverage, and 1,000 pages in under 3 s |
| `tests/extraction` | 76 | Locale number parsing (US, EU, space, Indian, negatives), dates in EN/DE/FR/ES, currency detection and bare `$`; rules extraction and missing fields; grounding nulls made-up evidence; JSON parsing of LLM replies; fake client; in-memory and **Redis** rate limiters (two workers share one quota; exact token budget); cache hits skip the LLM; 429 and invalid-JSON paths; LLM asked only for missing fields; **prompt injection does not change the total**; HTTP client sends no `thinkingConfig`, retries 5xx, does not retry 400/429, skips "thought" parts |
| `tests/validation` | 20 | Clean invoice has no issues; missing required fields are errors; missing customer/tax are info (no tax when subtotal = total); rounding tolerance; line items vs subtotal; wrong total; qty × price warning; negatives; invalid and implausible dates; low confidence, low OCR confidence, ambiguous currency, evidence notes; supplier normalisation; exact duplicate excluding itself; fuzzy duplicate with a supplier typo, and by total within 3 days; different supplier is not a duplicate; PDF-Excel match/mismatch/missing; PDF-PDF; 5,000-row batch in under 1 s; no `float(` in the package |
| `tests/api` | 15 | Health without a key; wrong key → `UNAUTHORIZED` with the standard error body; 404 bodies; PDF and CSV reach COMPLETED with SUCCEEDED events for all 4 stages; a batch with bad files (`FILE_TYPE_UNSUPPORTED`, `FILE_EMPTY`) does not fail the good one; `FILE_TOO_LARGE`; corrupt PDF → FAILED `FILE_CORRUPT` at parse; `OCR_FAILED` then reprocess → COMPLETED; unexpected error → `INTERNAL_ERROR`, then reprocess from index; re-running parse/extract/validate does not duplicate rows; wrong total → NEEDS_REVIEW, then a correction → CORRECTED/COMPLETED with history; exact duplicate flagged and resolvable; keyword/semantic/hybrid search and filters; PDF-vs-Excel cross-check (match/mismatch/missing, no stacked issues); stats |
| `tests/test_contracts_and_storage.py` | 5 | Contract models, evidence requirement, Decimal strings, storage path safety |
| `tools/datagen/tests` | 5 | Generator determinism and label schema |

End-to-end measurements on the labeled dataset are in [EVALUATION.md](EVALUATION.md).
