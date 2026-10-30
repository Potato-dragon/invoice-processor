## Run `test-real-llm` (split: test, 46 documents, LLM_FAKE=false)

### Field accuracy (pipeline output vs labels)

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| invoice_number | 33 | 36 | 91.7% |
| invoice_date | 31 | 36 | 86.1% |
| supplier_name | 32 | 36 | 88.9% |
| customer_name | 34 | 36 | 94.4% |
| subtotal | 31 | 36 | 86.1% |
| tax | 33 | 36 | 91.7% |
| total | 35 | 36 | 97.2% |
| currency | 36 | 36 | 100.0% |

Overall: **92.0%**

| Document group | Correct | Total | Accuracy |
|---|---|---|---|
| digital | 148 | 152 | 97.4% |
| receipt | 24 | 24 | 100.0% |
| receipt_scan | 16 | 16 | 100.0% |
| scan_fair | 29 | 32 | 90.6% |
| scan_good | 30 | 32 | 93.8% |
| scan_poor | 18 | 32 | 56.2% |

### Outcomes

| Metric | Value |
|---|---|
| Status matches expected | 87.0% |
| Success rate (expected-good files that finished) | 100.0% |
| Unexpected failure rate | 0.0% |
| Failure files with the expected error code | 100.0% |
| Invoices that needed an LLM call | 6/36 = 16.7% |
| Seeded errors flagged (recall) | 8/8 = 100.0% |
| Clean documents sent to review (end to end) | 6/28 = 21.4% |
| Validator false positives (clean and correctly extracted, still flagged) | 0/16 = 0.0% |
| Segmentation precision / recall | None% / None% |
| PDF-vs-Excel cross-check accuracy | 5/8 = 62.5% |
| Wall time (upload to last result) | 410.9 s |

### Processing time (sum of stage durations)

| Measure | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| per document (ms) | 37 | 20406.2 | 63 | 125791 | 272386 |
| per page (ms) | 36 | 20955.4 | 66.5 | 125791.0 | 272386.0 |
| digital (ms/doc) | 19 | 2493.8 | 55 | 1237 | 44250 |
| receipt (ms/doc) | 3 | 42 | 44 | 46 | 46 |
| receipt_scan (ms/doc) | 2 | 415.5 | 415.5 | 481 | 481 |
| scan_fair (ms/doc) | 4 | 811.8 | 816.0 | 899 | 899 |
| scan_good (ms/doc) | 4 | 17809.5 | 1032.0 | 68519 | 68519 |
| scan_poor (ms/doc) | 4 | 158047.2 | 140899.5 | 272386 | 272386 |
| spreadsheet (ms/doc) | 1 | 17 | 17 | 17 | 17 |

### Documents whose status differed from expected

| Doc | Group | Expected | Actual | Exp. code | Actual code | Notes |
|---|---|---|---|---|---|---|
| syn_072 | scan_good | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (good) |
| syn_074 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned TIFF (fair) |
| syn_075 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned PDF (poor) |
| syn_076 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (poor) |
| syn_080 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (fair) |
| syn_082 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned TIFF (poor) |

