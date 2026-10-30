## Run `test-fake` (split: test, 46 documents, LLM_FAKE=true)

### Field accuracy (pipeline output vs labels)

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| invoice_number | 32 | 36 | 88.9% |
| invoice_date | 30 | 36 | 83.3% |
| supplier_name | 32 | 36 | 88.9% |
| customer_name | 34 | 36 | 94.4% |
| subtotal | 31 | 36 | 86.1% |
| tax | 33 | 36 | 91.7% |
| total | 33 | 36 | 91.7% |
| currency | 36 | 36 | 100.0% |

Overall: **90.6%**

| Document group | Correct | Total | Accuracy |
|---|---|---|---|
| digital | 148 | 152 | 97.4% |
| receipt | 24 | 24 | 100.0% |
| receipt_scan | 16 | 16 | 100.0% |
| scan_fair | 29 | 32 | 90.6% |
| scan_good | 29 | 32 | 90.6% |
| scan_poor | 15 | 32 | 46.9% |

### Outcomes

| Metric | Value |
|---|---|
| Status matches expected | 84.8% |
| Success rate (expected-good files that finished) | 100.0% |
| Unexpected failure rate | 0.0% |
| Failure files with the expected error code | 100.0% |
| Invoices that needed an LLM call | 6/36 = 16.7% |
| Seeded errors flagged (recall) | 8/8 = 100.0% |
| Clean documents sent to review (end to end) | 7/28 = 25.0% |
| Validator false positives (clean and correctly extracted, still flagged) | 0/16 = 0.0% |
| Segmentation precision / recall | None% / None% |
| PDF-vs-Excel cross-check accuracy | 5/8 = 62.5% |
| Wall time (upload to last result) | 16.4 s |

### Processing time (sum of stage durations)

| Measure | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| per document (ms) | 37 | 697.2 | 97 | 3843 | 5210 |
| per page (ms) | 36 | 697.6 | 103.0 | 3843.0 | 5210.0 |
| digital (ms/doc) | 19 | 80.9 | 62 | 182 | 223 |
| receipt (ms/doc) | 3 | 57 | 47 | 83 | 83 |
| receipt_scan (ms/doc) | 2 | 424.5 | 424.5 | 437 | 437 |
| scan_fair (ms/doc) | 4 | 908.2 | 893.0 | 997 | 997 |
| scan_good (ms/doc) | 4 | 1235.5 | 1331.0 | 1363 | 1363 |
| scan_poor (ms/doc) | 4 | 3659.5 | 4245.5 | 5210 | 5210 |
| spreadsheet (ms/doc) | 1 | 24 | 24 | 24 | 24 |

### Documents whose status differed from expected

| Doc | Group | Expected | Actual | Exp. code | Actual code | Notes |
|---|---|---|---|---|---|---|
| syn_072 | scan_good | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (good) |
| syn_074 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned TIFF (fair) |
| syn_075 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned PDF (poor) |
| syn_076 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (poor) |
| syn_080 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (fair) |
| syn_081 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned PNG (poor) |
| syn_082 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned TIFF (poor) |

