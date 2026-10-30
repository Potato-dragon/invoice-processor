# Status board (update your own row when you finish or get blocked)

| Lane | Owner folder | Brief | Branch | State | Notes |
|---|---|---|---|---|---|
| A | backend/app (core), docker-compose.yml, infra | handoffs/A1.md, handoffs/A2.md | lane-a/skeleton | IN PROGRESS | A1 (compose, config, DB, migrations, contracts, storage) merged. A2 (API, pipeline, search) next. |
| F | tools/datagen, data/ | handoffs/F1.md, handoffs/F2.md | lane-f/datagen | IN PROGRESS | F1 merged: 6 layouts, 32 digital PDFs (22 dev, 10 test), labels, manifest, verify.py. F2 (scans, spreadsheets, errors, receipts, multi-invoice) next. |
| B | backend/app/parsing | handoffs/B-parsing.md | lane-b/parsing | NOT STARTED | |
| C | backend/app/extraction | handoffs/C-extraction.md | lane-c/extraction | DONE | Merged. Open: Redis limiter check, one real Gemma call, accuracy on dev split. |
| D | backend/app/validation | handoffs/D-validation.md | lane-d/validation | NOT STARTED | |
| E | frontend | (not written yet) | lane-e/frontend | NOT STARTED | |

## Gates
- Day 1: `docker compose up` works, upload via API runs the stub pipeline end to end, 40+ synthetic docs with ground truth exist.
- Day 2: every file type yields JSON + issues, failures return coded errors, baseline metrics exist.
- Day 3: all features demoable incl. search and cross-checks; 1,000-page PDF completes; prompts/rules frozen.
- Day 4: fresh clone runs in 10 minutes, final test run done once, report + walkthrough done.
