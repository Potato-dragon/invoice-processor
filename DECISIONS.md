# Design decisions

1. **Python end to end (FastAPI) with Next.js frontend.** The brief allows alternatives. One language for OCR, pandas and LLM glue saves time and avoids a cross-language boundary.
2. **Postgres + pgvector for everything** (relational, full-text, vectors). A dedicated vector DB is unnecessary at this scale; scale-up path documented in README.
3. **Redis + RQ** instead of Celery/BullMQ: simpler to run and debug solo; same guarantees needed here (retries, separate queues).
4. **Free-tier LLM strategy.** Rules first, then Gemma 4 (high daily allowance, low tokens/min), then Gemini Flash-Lite for hard cases; every call cached; one shared rate limiter. Only synthetic/public documents are ever sent (free tier data may be used by the provider).
5. **Local embeddings with fastembed (ONNX)** rather than PyTorch or API embeddings: small disk footprint, no daily quota.
6. **Per-invoice extraction, per-page OCR.** Long PDFs are segmented into invoices before extraction so LLM calls stay small.
7. **Grounding over trust.** Every extracted value carries evidence; values not found in the source are nulled and flagged.
8. **PyMuPDF (AGPL)** is used for PDF rendering/text; noted in README. `pypdfium2` is the permissive swap.
9. **Money is Decimal / strings, never float.**
10. Receipts are treated as invoice-like documents using the same extraction object. Receipt number goes in invoice_number, merchant in supplier_name, customer_name is null unless printed. Marked by layout prefix "receipt_" and notes "doc_type=receipt" in the manifest (no contract change).
11. Issue severity: missing invoice_number, invoice_date, supplier_name or total = error. Missing customer_name or tax = info. CURRENCY_AMBIGUOUS = error (a human must pick the currency). Any error => NEEDS_REVIEW.
12. **Line-aware rules extractor** (rewritten 30 Oct). The first version expected "Label: value" on one line, which scored 39.5% on the generated PDFs. Real PDF text layers and OCR put values on the next line or in the next cell. The rewrite reached 98.1% on digital PDFs without any LLM.
13. **OCR rows from word boxes.** Tesseract's own blocks follow columns, which separates labels from right-aligned values. Words are regrouped by visual row, with tab-separated cells. A second "rescue" preprocessing pass (contrast stretch + non-local-means) runs only when confidence is below 0.75. OCR is English-only by default (`OCR_LANGS`), because four languages made it about 20x slower for little gain on Latin-script invoices.
14. **US-style vs day-first dates.** An ambiguous date (03/04/2026) is resolved from another unambiguous date in the document, otherwise from US cues in the supplier block (USA, a state + ZIP, USD). It gets confidence 0.75, not 0.9. This is a known residual error source.
15. **No `thinkingConfig` for Gemma.** A real call returned HTTP 400 ("Thinking budget is not supported for this model"). The client retries 5xx and timeouts (3 attempts with backoff) and skips "thought" parts of the reply.
16. **LLM never erases a rules value.** If the LLM answer is empty, has no evidence, or its evidence is not in the text, the rules value (even at low confidence) is kept. If both agree, confidence goes up.
17. **Duplicates are flagged against older invoices only** (by upload time, then page). Validation also flags newer copies that finished first, so detection does not depend on worker order.
18. **Placeholder customers** ("Standard Customer Sale", "Walk-in customer", "N/A") count as no customer.
19. **Rejected uploads are recorded** as FAILED documents (see CONTRACT_CHANGES 2).
20. **Generated USD documents print "US$"**. Only the deliberately ambiguous documents print a bare "$". INR/BDT print ISO codes because the PDF font has no ₹/৳ glyph (they came out as "I" in the text layer, so the label could never be grounded).
21. **SimpleWorker** (no fork per job), so OCR and embedding models stay loaded in memory.
22. **Vision fallback (31 Oct).** For OCR'd pages with confidence below 0.80, or with required fields missing, the LLM gets the page image (the first and last page of the invoice, grayscale, max 2,000 px) instead of OCR text. Measured on a 510 px invoice: Tesseract 0/7 fields, Gemma 4 vision 7/7. A vision value replaces a rules value only if that value is missing, below 0.7, or came from garbled OCR (below 0.6). Values not confirmed in the OCR text get confidence 0.55 plus a warning. Digital PDFs never use vision, because their text layer is exact.
23. **Rules first, but ask the LLM for every weak field.** One call costs the same whatever it asks for, so when the LLM is called, it is asked for all null or low-confidence fields (customer, subtotal and tax included). It is also called when 3+ fields are weak (an unfamiliar layout), not only when a required field is missing.
24. **Confidence capped by OCR confidence.** A field read from a page with OCR confidence c < 0.8 cannot have confidence above c, so poor scans go to the LLM or vision and get review warnings.
25. **Fake LLM answers are never cached.** An earlier fake-mode run had filled `llm_cache`, and later real runs silently reused those answers.
26. **Grounding uses whole-word matching.** Evidence "Total: 100.00" was being "found" inside "Subtotal: 100.00".
27. **Small images are upscaled by pixel size** (to about 3,000 px on the long side, at most 4×) when the file declares no DPI. This is typical of screenshots.
28. **Image-read invoices always go to review (owner's decision, 31 Oct).** If any field came from the vision fallback and could not be confirmed in the OCR text, validation raises one `LOW_CONFIDENCE` *error* listing those fields, so the invoice becomes NEEDS_REVIEW even when its numbers add up. Correcting those fields, or marking the error checked, clears it. Reason: these values have no text evidence at all, so a person must confirm them before they count as data.
29. **Document status is computed under a row lock.** A reviewer clicking "Mark checked" while the index stage was finishing could have their change overwritten (lost update). Both paths now lock the document row, and recompute from fresh data, before writing its status.
