# Public real-world invoices (evaluation only)

15 documents: 11 real-world sample invoices and receipts, plus the 4 PNG renderings that ship with them. The source is the test suite of the **invoice2data** project, `tests/compare/`: <https://github.com/invoice-x/invoice2data>, MIT licence, copyright (c) 2015 Manuel Riel. See `LICENSE-invoice2data.md`.

These cover layouts our generator never produces:

- AWS statement-style invoice
- Odoo invoice (issuer and customer easily confused)
- Flipkart retail invoice (values printed before their labels)
- French legal-notice invoice and French telecom bill
- German hosting invoice (2 pages)
- Two Dutch Coolblue invoices ("Subtotaal" includes VAT)
- Indian hotel receipt
- Dutch Saeco invoice whose issuer name exists only inside an image

**The labels are ours, written by hand** from the visible document, following CONTRACTS section 7 and DECISIONS 10–11. Examples: a bare "$" means currency null; subtotal means the amount before tax. They are defined in `tools/datagen/real_sets.py`, with a note per document. invoice2data's own expected outputs (in `raw/`, not committed) use different conventions and were only used to settle ambiguous cases.

Rebuild: `python tools/datagen/real_sets.py`. Evaluate: `docker compose exec api python -m evaluation.run_eval --root public --split all --reset`.
