## Run `real-rules-before` (split: all, 2 documents, LLM_FAKE=true)

### Field accuracy (pipeline output vs labels)

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| invoice_number | 1 | 2 | 50.0% |
| invoice_date | 0 | 2 | 0.0% |
| supplier_name | 1 | 2 | 50.0% |
| customer_name | 0 | 2 | 0.0% |
| subtotal | 1 | 2 | 50.0% |
| tax | 1 | 2 | 50.0% |
| total | 1 | 2 | 50.0% |
| currency | 1 | 2 | 50.0% |

Overall: **37.5%**

| Document group | Correct | Total | Accuracy |
|---|---|---|---|
| digital | 6 | 8 | 75.0% |
| scan_image | 0 | 8 | 0.0% |

### Outcomes

| Metric | Value |
|---|---|
| Status matches expected | 0.0% |
| Success rate (expected-good files that finished) | 100.0% |
| Unexpected failure rate | 0.0% |
| Failure files with the expected error code | None% |
| Invoices that needed an LLM call | 1/2 = 50.0% |
| Seeded errors flagged (recall) | 0/0 = None% |
| Clean documents sent to review (end to end) | 1/2 = 50.0% |
| Validator false positives (clean and correctly extracted, still flagged) | 0/0 = None% |
| Segmentation precision / recall | None% / None% |
| PDF-vs-Excel cross-check accuracy | 0/0 = None% |
| Wall time (upload to last result) | 2.1 s |

### Processing time (sum of stage durations)

| Measure | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| per document (ms) | 2 | 819 | 819.0 | 1598 | 1598 |
| per page (ms) | 2 | 809.0 | 809.0 | 1598.0 | 1598.0 |
| digital (ms/doc) | 1 | 40 | 40 | 40 | 40 |
| scan_image (ms/doc) | 1 | 1598 | 1598 | 1598 | 1598 |

### Documents whose status differed from expected

| Doc | Group | Expected | Actual | Exp. code | Actual code | Notes |
|---|---|---|---|---|---|---|
| real_001 | scan_image |  | NEEDS_REVIEW |  |  | low-resolution screenshot (497 x 706 px); currency printed only as '(TK)' (Taka) |
| real_002 | digital |  | COMPLETED |  |  | Shopify bill, 2 pages; issuer block at the bottom; 'Account billed' customer label |

