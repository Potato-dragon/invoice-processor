# Real / Public Invoices

This folder is reserved for real or publicly available sample invoices (10 to 25 documents).

## Instructions
1. Place raw invoice files (`.pdf`, `.jpg`, `.png`, `.tiff`, `.xlsx`, `.csv`) in `data/real/samples/`.
2. For each document `<id>.<ext>`, create a corresponding ground-truth label file `data/real/labels/<id>.json`.
3. Labels must follow the CONTRACTS Section 10 format:
   - Ground truth values only (`value` fields populated with exact text/numbers, `null` where absent).
   - Money as decimal strings (e.g. `"123.45"`), never floats.
   - Dates in ISO `YYYY-MM-DD` format.
   - Line items with `description`, `quantity`, `unit_price`, `amount`.
   - Include `"invoice_count": 1` (or count for multi-invoice files).
4. Update or maintain `data/real/manifest.csv` with metadata matching `data/manifest.csv` schema.
