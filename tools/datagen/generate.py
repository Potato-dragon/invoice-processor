"""Main synthetic dataset generator CLI script.

Usage:
    python tools/datagen/generate.py [--seed SEED] [--data-dir PATH]
"""

import argparse
import csv
import json
import os
import random
import sys
from pathlib import Path

# Add project root to sys.path so tools.datagen imports work smoothly
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.datagen.config import GLOBAL_SEED
from tools.datagen.generators.digital_pdf import build_digital_pdf_dataset
from tools.datagen.layouts import render_invoice_pdf


def generate_all(seed: int = GLOBAL_SEED, data_dir: Path = None) -> None:
    if data_dir is None:
        data_dir = PROJECT_ROOT / "data"

    samples_dir = data_dir / "samples"
    labels_dir = data_dir / "labels"
    manifest_path = data_dir / "manifest.csv"

    samples_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)

    print(f"Generating synthetic invoice dataset (seed={seed})...")
    invoices = build_digital_pdf_dataset(rng)

    manifest_rows = []

    for invoice in invoices:
        pdf_path = samples_dir / invoice.filename
        label_path = labels_dir / f"{invoice.id}.json"

        # 1. Render PDF
        render_invoice_pdf(invoice, str(pdf_path))

        # 2. Write Ground Truth Label JSON
        label_data = invoice.to_label_dict()
        with open(label_path, "w", encoding="utf-8") as f:
            json.dump(label_data, f, indent=2, ensure_ascii=False)
            f.write("\n")

        # 3. Add to manifest
        manifest_rows.append(invoice.to_manifest_row())

    # Sort manifest rows deterministically by ID
    manifest_rows.sort(key=lambda r: r["id"])

    # 4. Write manifest.csv
    fieldnames = [
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

    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in manifest_rows:
            writer.writerow(row)

    print(f"Generation complete!")
    print(f"  Samples generated: {len(invoices)} in {samples_dir}")
    print(f"  Labels generated:  {len(invoices)} in {labels_dir}")
    print(f"  Manifest written:  {manifest_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic invoice dataset.")
    parser.add_argument("--seed", type=int, default=GLOBAL_SEED, help="Random seed for reproducibility")
    parser.add_argument("--data-dir", type=str, default=None, help="Root path for data directory")

    args = parser.parse_args()
    data_path = Path(args.data_dir).resolve() if args.data_dir else None
    generate_all(seed=args.seed, data_dir=data_path)


if __name__ == "__main__":
    main()
