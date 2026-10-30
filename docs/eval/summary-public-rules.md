## Run `public-rules` (split: all, 15 documents, LLM_FAKE=true)

### Field accuracy (pipeline output vs labels)

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| invoice_number | 10 | 15 | 66.7% |
| invoice_date | 14 | 15 | 93.3% |
| supplier_name | 8 | 15 | 53.3% |
| customer_name | 7 | 15 | 46.7% |
| subtotal | 8 | 15 | 53.3% |
| tax | 11 | 15 | 73.3% |
| total | 13 | 15 | 86.7% |
| currency | 13 | 15 | 86.7% |

Overall: **70.0%**

| Document group | Correct | Total | Accuracy |
|---|---|---|---|
| digital | 65 | 88 | 73.9% |
| scan_image | 19 | 32 | 59.4% |

### Outcomes

| Metric | Value |
|---|---|
| Status matches expected | 0.0% |
| Success rate (expected-good files that finished) | 100.0% |
| Unexpected failure rate | 0.0% |
| Failure files with the expected error code | None% |
| Invoices that needed an LLM call | 10/15 = 66.7% |
| Seeded errors flagged (recall) | 0/0 = None% |
| Clean documents sent to review (end to end) | 9/15 = 60.0% |
| Validator false positives (clean and correctly extracted, still flagged) | 1/1 = 100.0% |
| Segmentation precision / recall | None% / None% |
| PDF-vs-Excel cross-check accuracy | 0/0 = None% |
| Wall time (upload to last result) | 6.6 s |

### Processing time (sum of stage durations)

| Measure | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| per document (ms) | 15 | 549.2 | 63 | 1572 | 1753 |
| per page (ms) | 15 | 545.5 | 60.0 | 1572.0 | 1753.0 |
| digital (ms/doc) | 11 | 245.3 | 56 | 1178 | 1178 |
| scan_image (ms/doc) | 4 | 1385 | 1492.0 | 1753 | 1753 |

### Documents whose status differed from expected

| Doc | Group | Expected | Actual | Exp. code | Actual code | Notes |
|---|---|---|---|---|---|---|
| pub_001 | digital |  | COMPLETED |  |  | AmazonWebServices.pdf: statement-style invoice; currency stated in words ('in US Dollars') |
| pub_002 | digital |  | NEEDS_REVIEW |  |  | AzureInterior.pdf: Odoo demo invoice: issuer is 'YourCompany', billed partner is Azure Interior; bare $ -> currency null |
| pub_003 | digital |  | COMPLETED |  |  | FlipkartInvoice.pdf: values printed before their labels in the text layer; 'Rs' in the body |
| pub_004 | digital |  | NEEDS_REVIEW |  |  | NetpresseInvoice.pdf: French; issuer only in the footer |
| pub_005 | digital |  | COMPLETED |  |  | QualityHosting.pdf: German, 2 pages; only 'Total EUR' printed (no tax line) |
| pub_006 | digital |  | NEEDS_REVIEW |  |  | SammyMaystoneLinesTest.pdf: labels and values in separate columns; bare $ -> currency null |
| pub_007 | digital |  | COMPLETED |  |  | coolblue1.pdf: Dutch; 'Subtotaal' is VAT-inclusive, the pre-tax amount is 'Exclusief BTW' |
| pub_008 | digital |  | NEEDS_REVIEW |  |  | coolblue2.pdf: Dutch; as coolblue1 |
| pub_009 | digital |  | COMPLETED |  |  | free_fiber.pdf: French telecom bill, 2 pages |
| pub_010 | digital |  | COMPLETED |  |  | oyo.pdf: hotel payment receipt: booking ID as number (DECISIONS 10); tax included, not shown |
| pub_011 | digital |  | NEEDS_REVIEW |  |  | saeco.pdf: Dutch; supplier name exists only inside an embedded image (text layer cannot find it) |
| pub_012 | scan_image |  | NEEDS_REVIEW |  |  | AmazonWebServices.png (image version): statement-style invoice; currency stated in words ('in US Dollars') |
| pub_013 | scan_image |  | NEEDS_REVIEW |  |  | FlipkartInvoice.png (image version): values printed before their labels in the text layer; 'Rs' in the body |
| pub_014 | scan_image |  | NEEDS_REVIEW |  |  | SammyMaystoneLinesTest.png (image version): labels and values in separate columns; bare $ -> currency null |
| pub_015 | scan_image |  | NEEDS_REVIEW |  |  | oyo.png (image version): hotel payment receipt: booking ID as number (DECISIONS 10); tax included, not shown |

