## Run `public-llm` (split: all, 15 documents, LLM_FAKE=false)

### Field accuracy (pipeline output vs labels)

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| invoice_number | 14 | 15 | 93.3% |
| invoice_date | 15 | 15 | 100.0% |
| supplier_name | 8 | 15 | 53.3% |
| customer_name | 13 | 15 | 86.7% |
| subtotal | 12 | 15 | 80.0% |
| tax | 15 | 15 | 100.0% |
| total | 14 | 15 | 93.3% |
| currency | 13 | 15 | 86.7% |

Overall: **86.7%**

| Document group | Correct | Total | Accuracy |
|---|---|---|---|
| digital | 75 | 88 | 85.2% |
| scan_image | 29 | 32 | 90.6% |

### Outcomes

| Metric | Value |
|---|---|
| Status matches expected | 0.0% |
| Success rate (expected-good files that finished) | 100.0% |
| Unexpected failure rate | 0.0% |
| Failure files with the expected error code | None% |
| Invoices that needed an LLM call | 14/15 = 93.3% |
| Seeded errors flagged (recall) | 0/0 = None% |
| Clean documents sent to review (end to end) | 8/15 = 53.3% |
| Validator false positives (clean and correctly extracted, still flagged) | 4/7 = 57.1% |
| Segmentation precision / recall | None% / None% |
| PDF-vs-Excel cross-check accuracy | 0/0 = None% |
| Wall time (upload to last result) | 173.6 s |

### Processing time (sum of stage durations)

| Measure | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| per document (ms) | 15 | 22559.3 | 740 | 101439 | 120170 |
| per page (ms) | 15 | 22556.3 | 740.0 | 101439.0 | 120170.0 |
| digital (ms/doc) | 11 | 26634 | 47 | 120170 | 120170 |
| scan_image (ms/doc) | 4 | 11354 | 1341.5 | 41993 | 41993 |

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
| pub_008 | digital |  | COMPLETED |  |  | coolblue2.pdf: Dutch; as coolblue1 |
| pub_009 | digital |  | NEEDS_REVIEW |  |  | free_fiber.pdf: French telecom bill, 2 pages |
| pub_010 | digital |  | COMPLETED |  |  | oyo.pdf: hotel payment receipt: booking ID as number (DECISIONS 10); tax included, not shown |
| pub_011 | digital |  | NEEDS_REVIEW |  |  | saeco.pdf: Dutch; supplier name exists only inside an embedded image (text layer cannot find it) |
| pub_012 | scan_image |  | NEEDS_REVIEW |  |  | AmazonWebServices.png (image version): statement-style invoice; currency stated in words ('in US Dollars') |
| pub_013 | scan_image |  | NEEDS_REVIEW |  |  | FlipkartInvoice.png (image version): values printed before their labels in the text layer; 'Rs' in the body |
| pub_014 | scan_image |  | NEEDS_REVIEW |  |  | SammyMaystoneLinesTest.png (image version): labels and values in separate columns; bare $ -> currency null |
| pub_015 | scan_image |  | COMPLETED |  |  | oyo.png (image version): hotel payment receipt: booking ID as number (DECISIONS 10); tax included, not shown |

