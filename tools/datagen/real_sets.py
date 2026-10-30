"""Hand-labelled real-world evaluation sets (no generation, only copying + labels).

- data/public/: 11 public sample invoices from the invoice2data project
  (MIT licence, https://github.com/invoice-x/invoice2data, tests/compare/),
  plus the 4 PNG renderings that project ships. Committed with attribution.
- data/real/: the owner's own invoices. Git-ignored (personal data).

Labels follow CONTRACTS section 7 / 10 and the project's decisions:
subtotal = amount before tax, total = amount payable, a bare "$" means
currency null (DECISIONS 11), receipts use the receipt/booking number as
invoice_number (DECISIONS 10). A field that is not printed is null.

Run:  python tools/datagen/real_sets.py
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "data"
FIELDS = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency"]

# (source file, label values in FIELDS order, notes)
PUBLIC = [
    ("AmazonWebServices.pdf", ["42183017", "2014-08-03", "Amazon Web Services, Inc.", "iViveLabs Limited", "4.11", "0.00", "4.11", "USD"],
     "statement-style invoice; currency stated in words ('in US Dollars')"),
    ("AzureInterior.pdf", ["INV/2023/03/0008", "2023-03-20", "YourCompany", "Azure Interior", "262.90", "16.94", "279.84", None],
     "Odoo demo invoice: issuer is 'YourCompany', billed partner is Azure Interior; bare $ -> currency null"),
    ("FlipkartInvoice.pdf", ["BLR_WFLD20151000982590", "2015-10-20", "WS Retail Services Pvt. Ltd.", "Anushrut Singh", "278.61", "40.39", "319.00", "INR"],
     "values printed before their labels in the text layer; 'Rs' in the body"),
    ("NetpresseInvoice.pdf", ["2022089083", "2022-11-28", "NETPRESSE", "ALEXINUX", "46.68", "9.34", "56.02", "EUR"],
     "French; issuer only in the footer"),
    ("QualityHosting.pdf", ["30064443", "2014-05-07", "QualityHosting AG", "iViveLabs Ltd.", None, None, "34.73", "EUR"],
     "German, 2 pages; only 'Total EUR' printed (no tax line)"),
    ("SammyMaystoneLinesTest.pdf", ["invoice_number_1", "2022-01-01", "Sammy Maystone", "Taylor Riddel", "127.50", "0.00", "127.50", None],
     "labels and values in separate columns; bare $ -> currency null"),
    ("coolblue1.pdf", ["993548900", "2014-04-19", "Coolblue B.V.", "Pino Bluebird", "593.36", "124.61", "717.97", "EUR"],
     "Dutch; 'Subtotaal' is VAT-inclusive, the pre-tax amount is 'Exclusief BTW'"),
    ("coolblue2.pdf", ["992288600", "2014-03-29", "Coolblue B.V.", "Pino Bluebird", "4053.67", "851.27", "4904.94", "EUR"],
     "Dutch; as coolblue1"),
    ("free_fiber.pdf", ["562044387", "2015-07-02", "Free Service Abonné", "de Lattre Alexis", "24.99", "5.00", "29.99", "EUR"],
     "French telecom bill, 2 pages"),
    ("oyo.pdf", ["IBZY2087", "2017-12-31", "Oravel Stays Private Limited", "Sanjay", None, None, "1939.00", "INR"],
     "hotel payment receipt: booking ID as number (DECISIONS 10); tax included, not shown"),
    ("saeco.pdf", ["VF1005193039", "2022-09-08", "e-Luscious Nederland B.V.", "Strategic Corp", "41.31", "8.68", "49.99", "EUR"],
     "Dutch; supplier name exists only inside an embedded image (text layer cannot find it)"),
]
PUBLIC_IMAGES = ["AmazonWebServices.png", "FlipkartInvoice.png", "SammyMaystoneLinesTest.png", "oyo.png"]

# The owner's own invoices: their labels live next to them in data/real/real_labels.json
# (git-ignored, personal data): [{"file", "values" (FIELDS order), "notes", "kind"}].
REAL_LABELS = ROOT / "real" / "real_labels.json"


def _label(values: list) -> dict:
    return {**{f: {"value": v} for f, v in zip(FIELDS, values)}, "line_items": [], "invoice_count": 1}


def _row(doc_id: str, filename: str, kind: str, values: list, notes: str, quality: str) -> dict:
    return {"id": doc_id, "filename": filename, "kind": kind, "layout": "real", "supplier": values[2] or "",
            "locale": "", "currency": values[7] or "", "quality": quality, "split": "test",
            "expected_status": "", "expected_error_code": "", "notes": notes}


def _write(target: Path, rows: list[dict], labels: dict[str, dict]) -> None:
    (target / "labels").mkdir(parents=True, exist_ok=True)
    for doc_id, label in labels.items():
        (target / "labels" / f"{doc_id}.json").write_text(json.dumps(label, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with open(target / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"{target}: {len(rows)} documents")


def build_public() -> None:
    raw, out = ROOT / "public" / "raw", ROOT / "public"
    (out / "samples").mkdir(parents=True, exist_ok=True)
    rows, labels = [], {}
    by_source = {}
    for n, (src, values, notes) in enumerate(PUBLIC, start=1):
        doc_id = f"pub_{n:03d}"
        shutil.copyfile(raw / src, out / "samples" / f"{doc_id}.pdf")
        rows.append(_row(doc_id, f"{doc_id}.pdf", "pdf", values, f"{src}: {notes}", "digital"))
        labels[doc_id] = _label(values)
        by_source[src.rsplit(".", 1)[0]] = (values, notes)
    for n, src in enumerate(PUBLIC_IMAGES, start=len(PUBLIC) + 1):
        doc_id = f"pub_{n:03d}"
        values, notes = by_source[src.rsplit(".", 1)[0]]
        shutil.copyfile(raw / src, out / "samples" / f"{doc_id}.png")
        rows.append(_row(doc_id, f"{doc_id}.png", "image", values, f"{src} (image version): {notes}", "image"))
        labels[doc_id] = _label(values)
    _write(out, rows, labels)


def build_real() -> None:
    out = ROOT / "real"
    if not REAL_LABELS.exists():
        print("skip data/real: no real_labels.json (private, not in git)")
        return
    rows, labels = [], {}
    for entry in json.loads(REAL_LABELS.read_text(encoding="utf-8")):
        filename, values, notes, kind = entry["file"], entry["values"], entry["notes"], entry["kind"]
        if not (out / "samples" / filename).exists():
            print(f"skip {filename}: not present (private, not in git)")
            continue
        doc_id = filename.rsplit(".", 1)[0]
        rows.append(_row(doc_id, filename, kind, values, notes, "image" if kind == "image" else "digital"))
        labels[doc_id] = _label(values)
    if rows:
        _write(out, rows, labels)


if __name__ == "__main__":
    build_public()
    build_real()
