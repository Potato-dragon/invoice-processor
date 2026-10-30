## Run `all-large` (split: all, 108 documents, LLM_FAKE=true)

### Field accuracy (pipeline output vs labels)

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| invoice_number | 92 | 102 | 90.2% |
| invoice_date | 86 | 102 | 84.3% |
| supplier_name | 93 | 102 | 91.2% |
| customer_name | 95 | 102 | 93.1% |
| subtotal | 90 | 102 | 88.2% |
| tax | 94 | 102 | 92.2% |
| total | 93 | 102 | 91.2% |
| currency | 96 | 102 | 94.1% |

Overall: **90.6%**

| Document group | Correct | Total | Accuracy |
|---|---|---|---|
| digital | 425 | 432 | 98.4% |
| multi_invoice | 62 | 64 | 96.9% |
| receipt | 48 | 48 | 100.0% |
| receipt_scan | 29 | 32 | 90.6% |
| scan_fair | 71 | 80 | 88.8% |
| scan_good | 72 | 80 | 90.0% |
| scan_poor | 32 | 80 | 40.0% |

### Outcomes

| Metric | Value |
|---|---|
| Status matches expected | 81.5% |
| Success rate (expected-good files that finished) | 100.0% |
| Unexpected failure rate | 0.0% |
| Failure files with the expected error code | 100.0% |
| Invoices that needed an LLM call | 25/102 = 24.5% |
| Seeded errors flagged (recall) | 18/20 = 90.0% |
| Clean documents sent to review (end to end) | 18/75 = 24.0% |
| Validator false positives (clean and correctly extracted, still flagged) | 0/50 = 0.0% |
| Segmentation precision / recall | 100.0% / 100.0% |
| PDF-vs-Excel cross-check accuracy | 32/36 = 88.9% |
| Wall time (upload to last result) | 45.3 s |

### Processing time (sum of stage durations)

| Measure | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| per document (ms) | 99 | 814.4 | 92 | 4261 | 5043 |
| per page (ms) | 95 | 820.8 | 92.0 | 4261.0 | 5043.0 |
| digital (ms/doc) | 54 | 111.3 | 64.0 | 117 | 1195 |
| multi_invoice (ms/doc) | 1 | 1904 | 1904 | 1904 | 1904 |
| receipt (ms/doc) | 6 | 54.2 | 50.5 | 84 | 84 |
| receipt_scan (ms/doc) | 4 | 419.2 | 417.5 | 450 | 450 |
| scan_fair (ms/doc) | 10 | 1926.3 | 1301.0 | 4697 | 4697 |
| scan_good (ms/doc) | 10 | 1119.3 | 1039.0 | 1875 | 1875 |
| scan_poor (ms/doc) | 10 | 4004.9 | 4148.5 | 5043 | 5043 |
| spreadsheet (ms/doc) | 4 | 52.5 | 25.0 | 145 | 145 |

### 1,000-page PDF

| Metric | Value |
|---|---|
| Status | NEEDS_REVIEW |
| Pages | 1000 |
| Invoices (true / found) | 411 / 411 |
| Segmentation precision / recall | 100.0% / 100.0% |
| Processing time | 47.7 s (20.95 pages/s) |
| Stage time (s) | parse 23.7, extract 5.7, validate 1.8, index 16.6 |
| Field accuracy over all invoices | 97.7% |

### Documents whose status differed from expected

| Doc | Group | Expected | Actual | Exp. code | Actual code | Notes |
|---|---|---|---|---|---|---|
| syn_047 | receipt_scan | COMPLETED | NEEDS_REVIEW |  |  | doc_type=receipt scanned |
| syn_055 | scan_fair | NEEDS_REVIEW | COMPLETED |  |  | Scanned PNG (fair) |
| syn_056 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned TIFF (fair) |
| syn_057 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned PDF (poor) |
| syn_058 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (poor) |
| syn_061 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned PDF (fair) |
| syn_063 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned PNG (poor) |
| syn_064 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned TIFF (poor) |
| syn_065 | scan_good | COMPLETED | NEEDS_REVIEW |  |  | Scanned PDF (good) |
| syn_066 | scan_good | NEEDS_REVIEW | COMPLETED |  |  | Scanned JPG (good) |
| syn_067 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned PNG (fair) |
| syn_069 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned PDF (poor) |
| syn_070 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (poor) |
| syn_072 | scan_good | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (good) |
| syn_074 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned TIFF (fair) |
| syn_075 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned PDF (poor) |
| syn_076 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (poor) |
| syn_080 | scan_fair | COMPLETED | NEEDS_REVIEW |  |  | Scanned JPG (fair) |
| syn_081 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned PNG (poor) |
| syn_082 | scan_poor | COMPLETED | NEEDS_REVIEW |  |  | Scanned TIFF (poor) |

