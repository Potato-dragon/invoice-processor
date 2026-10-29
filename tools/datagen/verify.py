"""Self-check and validation script for synthetic datasets.

Confirms every sample has a label, manifest rows are consistent, files open,
and prints counts per kind/quality/split/expected_status.

Usage:
    python tools/datagen/verify.py [--data-dir PATH]
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def verify_dataset(data_dir: Path) -> bool:
    manifest_path = data_dir / "manifest.csv"
    samples_dir = data_dir / "samples"
    labels_dir = data_dir / "labels"

    print("=" * 60)
    print("RUNNING DATASET VERIFICATION (verify.py)")
    print(f"Data directory: {data_dir}")
    print("=" * 60)

    errors: list[str] = []

    # 1. Manifest file existence
    if not manifest_path.exists():
        print(f"FAIL: manifest.csv not found at {manifest_path}")
        return False

    # 2. Check manifest headers
    required_cols = [
        "id",
        "filename",
        "kind",
        "layout",
        "supplier",
        "locale",
        "currency",
        "quality",
        "split",
        "expected_status",
        "expected_error_code",
        "notes",
    ]

    manifest_rows = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != required_cols:
            errors.append(f"Manifest header mismatch: expected {required_cols}, got {reader.fieldnames}")
        for row in reader:
            manifest_rows.append(row)

    print(f"Manifest loaded: {len(manifest_rows)} rows found.")

    manifest_ids = {r["id"] for r in manifest_rows}
    manifest_files = {r["filename"] for r in manifest_rows}

    # 3. Verify each row
    date_regex = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    money_regex = re.compile(r"^-?\d+(\.\d{1,4})?$")

    dev_layouts = set()
    test_layouts = set()
    dev_suppliers = set()
    test_suppliers = set()

    counts_kind = Counter()
    counts_quality = Counter()
    counts_split = Counter()
    counts_status = Counter()

    for row in manifest_rows:
        doc_id = row["id"]
        filename = row["filename"]
        split = row["split"]
        layout = row["layout"]
        supplier = row["supplier"]

        counts_kind[row["kind"]] += 1
        counts_quality[row["quality"]] += 1
        counts_split[split] += 1
        counts_status[row["expected_status"]] += 1

        # Track layouts and suppliers by split
        if split == "dev":
            if layout:
                dev_layouts.add(layout)
            if supplier:
                dev_suppliers.add(supplier)
        elif split == "test":
            if layout:
                test_layouts.add(layout)
            if supplier:
                test_suppliers.add(supplier)
        else:
            errors.append(f"[{doc_id}] Invalid split '{split}' (must be 'dev' or 'test')")

        # Check sample file exists and is valid
        sample_file = samples_dir / filename
        if not sample_file.exists():
            errors.append(f"[{doc_id}] Sample file missing: {sample_file}")
        else:
            size = sample_file.stat().st_size
            if size == 0:
                errors.append(f"[{doc_id}] Sample file is empty (0 bytes): {filename}")
            if filename.endswith(".pdf"):
                with open(sample_file, "rb") as pf:
                    header = pf.read(5)
                    if header != b"%PDF-":
                        errors.append(f"[{doc_id}] PDF file has invalid magic bytes: {header}")

        # Check label file exists and is valid JSON
        label_file = labels_dir / f"{doc_id}.json"
        if not label_file.exists():
            errors.append(f"[{doc_id}] Label file missing: {label_file}")
            continue

        try:
            with open(label_file, "r", encoding="utf-8") as lf:
                label_data = json.load(lf)
        except Exception as e:
            errors.append(f"[{doc_id}] Label JSON decode error: {e}")
            continue

        # Check label schema per CONTRACTS section 10 and 7
        top_fields = [
            "invoice_number",
            "invoice_date",
            "supplier_name",
            "customer_name",
            "subtotal",
            "tax",
            "total",
            "currency",
        ]

        for field in top_fields:
            if field not in label_data:
                errors.append(f"[{doc_id}] Label missing field '{field}'")
            elif not isinstance(label_data[field], dict) or "value" not in label_data[field]:
                errors.append(f"[{doc_id}] Field '{field}' must be an object with a 'value' key")
            else:
                val = label_data[field]["value"]
                if val is not None and not isinstance(val, str):
                    errors.append(f"[{doc_id}] Field '{field}.value' must be str or null, got {type(val).__name__} ({val})")

                # Format checks
                if field == "invoice_date" and val is not None:
                    if not date_regex.match(val):
                        errors.append(f"[{doc_id}] invoice_date '{val}' is not ISO YYYY-MM-DD")
                elif field in ("subtotal", "tax", "total") and val is not None:
                    if not money_regex.match(val):
                        errors.append(f"[{doc_id}] Money field '{field}' has invalid decimal format: '{val}'")

        # Line items check
        if "line_items" not in label_data or not isinstance(label_data["line_items"], list):
            errors.append(f"[{doc_id}] Label missing 'line_items' list")
        else:
            for idx, item in enumerate(label_data["line_items"]):
                if not isinstance(item, dict):
                    errors.append(f"[{doc_id}] Line item #{idx} must be a dict")
                    continue
                for key in ("description", "quantity", "unit_price", "amount"):
                    if key not in item:
                        errors.append(f"[{doc_id}] Line item #{idx} missing '{key}'")
                    elif not isinstance(item[key], str):
                        errors.append(f"[{doc_id}] Line item #{idx} '{key}' must be str, got {type(item[key]).__name__}")
                    elif key in ("unit_price", "amount") and not money_regex.match(item[key]):
                        errors.append(f"[{doc_id}] Line item #{idx} '{key}' invalid decimal string: '{item[key]}'")

        if "invoice_count" not in label_data or not isinstance(label_data["invoice_count"], int):
            errors.append(f"[{doc_id}] Label missing int 'invoice_count'")

    # 4. Check for orphaned files in samples and labels
    if samples_dir.exists():
        for sf in samples_dir.iterdir():
            if sf.is_file() and sf.name not in manifest_files:
                errors.append(f"Orphan sample file not in manifest: {sf.name}")

    if labels_dir.exists():
        for lf in labels_dir.iterdir():
            if lf.is_file() and lf.suffix == ".json":
                lid = lf.stem
                if lid not in manifest_ids:
                    errors.append(f"Orphan label file not in manifest: {lf.name}")

    # 5. Check Dev / Test split disjointness
    layout_overlap = dev_layouts & test_layouts
    if layout_overlap:
        errors.append(f"Dev and Test layouts overlap! Shared layouts: {layout_overlap}")

    supplier_overlap = dev_suppliers & test_suppliers
    if supplier_overlap:
        errors.append(f"Dev and Test suppliers overlap! Shared suppliers: {supplier_overlap}")

    # 6. Print summary
    print("\n--- DATASET SUMMARY COUNTS ---")
    print(f"Total documents: {len(manifest_rows)}")

    print("\nCounts by Kind:")
    for k, v in sorted(counts_kind.items()):
        print(f"  {k:15}: {v}")

    print("\nCounts by Quality:")
    for q, v in sorted(counts_quality.items()):
        print(f"  {q:15}: {v}")

    print("\nCounts by Split:")
    for s, v in sorted(counts_split.items()):
        print(f"  {s:15}: {v}")

    print("\nCounts by Expected Status:")
    for st, v in sorted(counts_status.items()):
        print(f"  {st:15}: {v}")

    print("\nLayouts in Dev: ", sorted(dev_layouts))
    print("Layouts in Test: ", sorted(test_layouts))
    print(f"Dev suppliers ({len(dev_suppliers)}):  ", sorted(dev_suppliers))
    print(f"Test suppliers ({len(test_suppliers)}): ", sorted(test_suppliers))
    print("Disjoint Layouts Check:  ", "PASS" if not layout_overlap else "FAIL")
    print("Disjoint Suppliers Check:", "PASS" if not supplier_overlap else "FAIL")

    # 7. Final verdict
    print("\n" + "=" * 60)
    if errors:
        print(f"VERIFICATION FAILED with {len(errors)} error(s):")
        for err in errors[:25]:
            print(f"  - {err}")
        if len(errors) > 25:
            print(f"  ... and {len(errors) - 25} more errors.")
        return False
    else:
        print("VERIFICATION PASSED: All checks succeeded cleanly!")
        print("=" * 60)
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify dataset consistency and labels.")
    parser.add_argument("--data-dir", type=str, default=None, help="Root path for data directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve() if args.data_dir else PROJECT_ROOT / "data"
    success = verify_dataset(data_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
