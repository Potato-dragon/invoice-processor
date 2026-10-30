# Status board

| Lane | Owner folder | Brief | State | Notes |
|---|---|---|---|---|
| A | backend/app (core), docker-compose.yml | handoffs/A1.md, A2.md | DONE | API (upload, list, detail, events, file, pages, ledger, reprocess, invoices, PATCH corrections, issues, search, crosschecks, stats), stage runner, RQ worker, idempotent stages, retries. 15 API tests. |
| B | backend/app/parsing | handoffs/B-parsing.md | DONE | Text layer + OCR (deskew, Otsu, rescue pass, geometric rows), images incl. multi-frame TIFF, XLSX/XLS/CSV, segmenter. 26 tests. |
| C | backend/app/extraction | handoffs/C-extraction.md | DONE | Rules rewritten to be line-aware (39.5% → 98.1% on digital PDFs). Redis limiter now atomic and always used when REDIS_URL is set. thinkingBudget removed after a real 400. LLM merge keeps rules values. |
| D | backend/app/validation | handoffs/D-validation.md | DONE | Field, arithmetic, date, quality and duplicate checks; PDF-PDF / PDF-Excel cross-checks. 20 tests. |
| E | frontend | (built directly) | DONE | Next.js: upload, progress, document and invoice views, inline correction, review queue, search, cross-checks. |
| F | tools/datagen, data/ | handoffs/F1.md, F2.md | DONE | 108 docs (all file types), 30-page multi-invoice, 1,000-page generator (`--large`). verify.py passes. |
| Eval | backend/evaluation | (built directly) | DONE | `run_eval.py`; results in docs/EVALUATION.md and docs/eval/. |

Remaining for the human: record the walkthrough; optionally add 10–25 public invoices to `data/real/` with labels.
