# Rules for every coding agent (Codex, Antigravity)

You are one of several agents building this project in parallel. A human coordinator plus an architect (Claude) keep the design consistent. Follow these rules exactly.

## Before you write anything
1. Read `docs/ARCHITECTURE.md`, then `docs/CONTRACTS.md`, then your own brief in `docs/handoffs/`.
2. Do only what your brief asks. If something is unclear, make the smallest reasonable assumption and write it in the "Assumptions" section of your report. Do not stop to ask unless you are blocked.

## Ownership
- Edit only the folders your brief says you own.
- `docs/CONTRACTS.md` is FROZEN. Never edit it. If a contract is wrong or missing, add a note to `docs/CONTRACT_CHANGES.md` (what, why) and carry on with your best assumption.
- Never edit another lane's folder. If you need something from it, code against the interface in CONTRACTS.md and write a stub in your own folder for testing.

## Environment (important)
- The host is Windows with very little free disk space on C:. All services run in Docker; the repo lives on another drive.
- Keep dependencies light. No PyTorch, no TensorFlow, no large model downloads. Ask before adding any dependency larger than ~100 MB.
- Python 3.12. Money is `Decimal`, never `float`. Dates are ISO 8601 strings.
- Never commit secrets. Read config from environment variables (see CONTRACTS.md "Config"). `.env` is git-ignored; keep `.env.example` current.
- Free-tier LLM limits are tight. Never call a real LLM from tests. Use the cache or a fake client.

## Git
- Work on your own branch named in your brief. Small, frequent commits with clear messages. Never force-push. Never commit to `main`.
## Quota discipline
- Don't run `docker compose build/up` yourself. Write code, then list the exact commands the human should run. The human pastes back errors.
- Don't re-read files you already read. Don't print whole files in chat. Open only the files your brief lists.
- If a command fails twice, stop and report it instead of retrying.

## Done means
- Every acceptance check in your brief passes, and you ran them.
- You added or updated tests for what you built.
- You updated your row in `docs/STATUS.md`.
- You finish with a report in this exact format:

   ## Resuming (accounts rotate, you may have no memory)
   - Start: read STATUS.md, then `git log -10` and `git status` on your branch.
   - Commit WIP every ~15 minutes and after each task. Quota can end mid-task.
   - Before stopping or when told quota is low: commit, write "Next step:" in your STATUS row.

```
REPORT
Lane / task:
Branch:
What I built (3-6 bullets):
Files created or changed:
How to run it (PowerShell commands):
Acceptance checks: (each: PASS/FAIL + how verified)
Assumptions I made:
Contract gaps or problems found:
Not done / next:
```
