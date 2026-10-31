# invoice-ai: AI-powered document intelligence for invoices

Upload invoices, receipts, scans and spreadsheets. The system reads them (PDF text layer, OCR, or spreadsheet parsing), extracts the invoice fields, checks the arithmetic, finds duplicates, cross-checks PDFs against each other and against Excel, and gives people a web app to review and correct the results and to search everything.

- **Backend:** Python 3.12, FastAPI, PostgreSQL 16 + pgvector, Redis + RQ workers, Tesseract + OpenCV, PyMuPDF
- **Frontend:** Next.js 14 (React 18)
- **LLM:** Gemma 4 on the Google AI Studio free tier, used only when the rules are unsure. It reads the text, or, for poor scans, the page image. Every answer must be backed by text in the document, or it is dropped or marked for review.
- **Docs:** [Architecture and DB schema](docs/ARCHITECTURE.md) · [Evaluation report](docs/EVALUATION.md) · [Test results](docs/TEST_RESULTS.md) · [Design decisions](DECISIONS.md) · [API contracts](docs/CONTRACTS.md) · [AI use disclosure](docs/AI_DISCLOSURE.md)

## Quick start (Windows, PowerShell)

You need Docker Desktop and Git. Everything runs in containers, so no local Python or Node is needed to run the app.

```powershell
git clone https://github.com/Potato-dragon/invoice-processor.git
cd invoice-processor
Copy-Item .env.example .env
notepad .env        # set API_KEY to any long random string; GEMINI_API_KEY is optional
docker compose up -d --build
```

The first build takes a few minutes; it downloads Tesseract and a small (~67 MB) embedding model. When it finishes:

- Web app: <http://localhost:3000>
- API docs (Swagger): <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/health>

To stop: `docker compose down`. Data is kept in Docker volumes. Add `-v` to delete it.

> **Keep Docker data off a full C: drive:** in Docker Desktop, go to *Settings → Resources → Advanced → Disk image location* and choose a folder on D:.

### Settings (`.env`)

| Variable | Meaning | Default |
|---|---|---|
| `API_KEY` | Key every API call must send in the `X-API-Key` header. The web app's server adds it for you. | `change-me` |
| `GEMINI_API_KEY` | Google AI Studio key. Leave empty, or keep `LLM_FAKE=true`, to run rules-only. | empty |
| `LLM_FAKE` | `true` = never call a real LLM (used by all tests) | `true` |
| `LLM_PRIMARY_MODEL` / `LLM_FALLBACK_MODEL` | Model names | `gemma-4-31b-it` / `gemma-4-26b-a4b-it` |
| `LLM_PRIMARY_RPM/TPM/RPD`, `LLM_FALLBACK_RPM/TPM/RPD` | Free-tier limits enforced by the shared Redis rate limiter | 30 / 16000 / 14400 |
| `MAX_UPLOAD_MB`, `MAX_PAGES`, `OCR_DPI` | Upload limits and OCR resolution | 50, 1500, 300 |
| `WORKER_REPLICAS` | Number of background workers | 2 |

Only synthetic or public documents should be processed with a real free-tier key, because Google may use free-tier data for training.

## Using the API (PowerShell)

```powershell
$h = @{ "X-API-Key" = "<your API_KEY>" }

# Upload one or many files (multipart field "files")
curl.exe -H "X-API-Key: <your API_KEY>" -F "files=@data/samples/syn_001.pdf" -F "files=@data/samples/syn_095.xlsx" http://localhost:8000/api/documents

Invoke-RestMethod -Headers $h "http://localhost:8000/api/documents?status=NEEDS_REVIEW"
Invoke-RestMethod -Headers $h "http://localhost:8000/api/documents/<id>"           # status, stage, invoices
Invoke-RestMethod -Headers $h "http://localhost:8000/api/documents/<id>/events"    # processing history
Invoke-RestMethod -Headers $h "http://localhost:8000/api/invoices/<invoice id>"    # fields, evidence, issues
Invoke-RestMethod -Headers $h -Method Patch -ContentType "application/json" -Body '{"total":"137.50"}' "http://localhost:8000/api/invoices/<invoice id>"
Invoke-RestMethod -Headers $h -Method Post "http://localhost:8000/api/documents/<id>/reprocess"   # resume from the failed stage
Invoke-RestMethod -Headers $h "http://localhost:8000/api/search?q=freight&mode=hybrid&currency=USD&min_total=100"
Invoke-RestMethod -Headers $h -Method Post -ContentType "application/json" -Body '{"kind":"PDF_EXCEL"}' "http://localhost:8000/api/crosschecks/run"
Invoke-RestMethod -Headers $h "http://localhost:8000/api/stats"
```

| Endpoint | Purpose |
|---|---|
| `POST /api/documents` | Upload many files. Each file gets its own result; a bad file does not fail the batch. |
| `GET /api/documents`, `GET /api/documents/{id}` | List (filter by `status`, `kind`, `q`) and detail |
| `GET /api/documents/{id}/events` · `/file` · `/pages` · `/ledger` | Processing history, original file, extracted page text, spreadsheet rows |
| `POST /api/documents/{id}/reprocess[?from=parse\|extract\|validate\|index]` | Re-run a failed or finished document |
| `GET /api/invoices/{id}`, `PATCH /api/invoices/{id}` | Invoice with fields, evidence, line items and issues; manual correction (re-validates and re-indexes) |
| `GET /api/issues`, `POST /api/issues/{id}/resolve` | Review queue; mark an issue as checked |
| `GET /api/search` | `q`, `mode=keyword\|semantic\|hybrid`, plus filters `supplier, currency, date_from, date_to, min_total, max_total, review_status` |
| `POST /api/crosschecks/run`, `GET /api/crosschecks` | PDF↔PDF and PDF↔Excel comparison |
| `GET /api/stats` | Counts, success/failure rates, average stage times |

Every error has the same body: `{"error": {"code": "FILE_CORRUPT", "message": "..."}}`, using the codes in [CONTRACTS.md](docs/CONTRACTS.md).

## Tests

```powershell
docker compose exec api python -m pytest -q
```

The tests use a separate `invoice_test` database, run the pipeline inline, and never call a real LLM. The 154 tests cover parsing, OCR, spreadsheets, extraction, validation, the API and failure cases. See [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md).

## Test data

`data/samples/` holds 108 synthetic documents with exact ground truth in `data/labels/` and an index in `data/manifest.csv`. They include digital PDFs in 6 layouts, receipts, scans (PDF, JPG, PNG, TIFF at good/fair/poor quality), XLSX/XLS/CSV ledgers, seeded errors, failure files, a prompt-injection invoice, and a 30-page multi-invoice PDF. Layouts and suppliers in the `test` split never appear in `dev`.

To regenerate the data, or to build the 1,000-page PDF (git-ignored, written to `data/samples_large/`):

```powershell
python -m venv tools/datagen/.venv
.\tools\datagen\.venv\Scripts\pip install -r tools/datagen/requirements.txt
.\tools\datagen\.venv\Scripts\python tools/datagen/generate.py            # 108 documents, deterministic (seed 42)
.\tools\datagen\.venv\Scripts\python tools/datagen/generate.py --large    # + 1,000 pages / 411 invoices
.\tools\datagen\.venv\Scripts\python tools/datagen/verify.py
```

Real or public invoices for your own checks go in `data/real/` (git-ignored; see its README).

## Evaluation

```powershell
docker compose exec api python -m evaluation.run_eval --split test --reset            # rules + fake LLM
docker compose exec api python -m evaluation.run_eval --split all --reset --large     # everything + 1,000-page PDF
docker compose exec api python -m evaluation.run_eval --root public --split all --reset  # 15 real public invoices
```

The runner uploads the labeled files through the real API, waits for the workers, and compares the results with ground truth. `--reset` empties the database first. `--root public` uses the hand-labelled real-world invoices in `data/public/`, and `--root real` uses your own invoices in `data/real/` (git-ignored). Results go to `docs/eval/`. The numbers are in [docs/EVALUATION.md](docs/EVALUATION.md).

Headline numbers: digital synthetic PDFs 98.4% field accuracy (rules only); real public invoices 70.0% rules only and **86.7% with Gemma**; 1,000 pages in 48 s.

## Project layout

```
backend/app/
  main.py, api/        REST API (FastAPI), auth, rate limits, error bodies
  pipeline.py, jobs.py, worker.py   stage runner, Redis queues, worker process
  parsing/             PDF text layer, OCR (Tesseract + OpenCV), images, spreadsheets, invoice segmenter
  extraction/          rules extractor, grounding, LLM client, shared rate limiter, cache, prompts
  validation/          field/arithmetic/date checks, duplicates, cross-checks
  embeddings.py        local fastembed model for semantic search
  models.py, alembic/  database schema and migrations
backend/evaluation/    end-to-end evaluation runner
backend/tests/         pytest suites
frontend/              Next.js web app
tools/datagen/         synthetic dataset generator
data/                  samples, labels, manifest
docs/                  architecture, contracts, evaluation, prompts, handoffs
```

## Security notes

- API key on every endpoint except health (constant-time compare), a per-key rate limit on upload and search, and the same error body on every error path.
- The browser never sees the key: the web app calls its own server, which adds it.
- File type is decided by magic bytes, never by extension. Size and page limits, encrypted and corrupt files are rejected with coded errors. Stored file names are random keys, never user paths.
- Document text is treated as data. LLM prompts wrap it in delimiters and say it must not be followed, and any value the LLM returns must appear in the document text (prompt-injection test included).
- No secrets in the repo: `.env` is git-ignored.

## Licences

PyMuPDF is AGPL-3.0. For closed-source use, swap in `pypdfium2` for rendering and `pypdf` for text. All other dependencies are permissive.
