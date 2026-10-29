# Status board (update your own row when you finish or get blocked)

| Lane | Owner folder | Brief | Branch | State | Notes |
|---|---|---|---|---|---|
| A | backend/app (core), docker-compose.yml, infra | handoffs/A-backend-skeleton.md | lane-a/skeleton | NOT STARTED | |
| F | tools/datagen, data/ | handoffs/F-test-data.md | lane-f/datagen | IN PROGRESS | Tasks 1-3, 10-12 done: 6 layouts, 32 digital PDFs (22 dev, 10 test), labels, manifest, verify.py pass. Next step: Tasks 4-9 (scanned docs, spreadsheets, errors, multi-page PDFs). |
| B | backend/app/parsing | (not written yet) | lane-b/parsing | NOT STARTED | |
| C | backend/app/extraction | (not written yet) | lane-c/extraction | NOT STARTED | |
| D | backend/app/validation | (not written yet) | lane-d/validation | NOT STARTED | |
| E | frontend | (not written yet) | lane-e/frontend | NOT STARTED | |

## Gates
- Day 1: `docker compose up` works, upload via API runs the stub pipeline end to end, 40+ synthetic docs with ground truth exist.
- Day 2: every file type yields JSON + issues, failures return coded errors, baseline metrics exist.
- Day 3: all features demoable incl. search and cross-checks; 1,000-page PDF completes; prompts/rules frozen.
- Day 4: fresh clone runs in 10 minutes, final test run done once, report + walkthrough done.
