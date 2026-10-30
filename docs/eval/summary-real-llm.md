## Run `real-llm` (split: all, 2 documents, LLM_FAKE=false)

### Field accuracy (pipeline output vs labels)

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| invoice_number | 2 | 2 | 100.0% |
| invoice_date | 2 | 2 | 100.0% |
| supplier_name | 1 | 2 | 50.0% |
| customer_name | 2 | 2 | 100.0% |
| subtotal | 2 | 2 | 100.0% |
| tax | 2 | 2 | 100.0% |
| total | 2 | 2 | 100.0% |
| currency | 2 | 2 | 100.0% |

Overall: **93.8%**

| Document group | Correct | Total | Accuracy |
|---|---|---|---|
| digital | 8 | 8 | 100.0% |
| scan_image | 7 | 8 | 87.5% |

### Outcomes

| Metric | Value |
|---|---|
| Status matches expected | 0.0% |
| Success rate (expected-good files that finished) | 100.0% |
| Unexpected failure rate | 0.0% |
| Failure files with the expected error code | None% |
| Invoices that needed an LLM call | 2/2 = 100.0% |
| Seeded errors flagged (recall) | 0/0 = None% |
| Clean documents sent to review (end to end) | 0/2 = 0.0% |
| Validator false positives (clean and correctly extracted, still flagged) | 0/1 = 0.0% |
| Segmentation precision / recall | None% / None% |
| PDF-vs-Excel cross-check accuracy | 0/0 = None% |
| Wall time (upload to last result) | 4.2 s |

### Processing time (sum of stage durations)

| Measure | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| per document (ms) | 2 | 1995.5 | 1995.5 | 2741 | 2741 |
| per page (ms) | 2 | 1683.0 | 1683.0 | 2741.0 | 2741.0 |
| digital (ms/doc) | 1 | 1250 | 1250 | 1250 | 1250 |
| scan_image (ms/doc) | 1 | 2741 | 2741 | 2741 | 2741 |

### Documents whose status differed from expected

| Doc | Group | Expected | Actual | Exp. code | Actual code | Notes |
|---|---|---|---|---|---|---|
| real_001 | scan_image |  | COMPLETED |  |  | low-resolution screenshot (497 x 706 px); currency printed only as '(TK)' (Taka) |
| real_002 | digital |  | COMPLETED |  |  | Shopify bill, 2 pages; issuer block at the bottom; 'Account billed' customer label |

