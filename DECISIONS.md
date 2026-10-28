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
