"""Rules-only extraction accuracy on the labeled data (no LLM, no DB).

Run:  docker compose exec api python scripts/eval_rules.py [dev|test|all] [-v]
Reads DATA_DIR (default /data/repo) manifest, samples and labels.
"""
import csv
import json
import os
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation

from app.contracts import PipelineError
from app.extraction.ground import ground_result
from app.extraction.rules import extract_by_rules
from app.parsing import parse_document

FIELDS = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency"]
MONEY = {"subtotal", "tax", "total"}


def norm(field, v):
    if v is None:
        return None
    if field in MONEY:
        try:
            return Decimal(str(v)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return str(v)
    s = " ".join(str(v).split()).lower().rstrip(".")
    return s


def main():
    split = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dev"
    verbose = "-v" in sys.argv
    root = os.getenv("DATA_DIR", "/data/repo")
    rows = list(csv.DictReader(open(os.path.join(root, "manifest.csv"), encoding="utf-8")))
    rows = [r for r in rows if (split == "all" or r["split"] == split) and r["kind"] in ("pdf", "image") and r["expected_status"] != "FAILED"]
    hit, seen = Counter(), Counter()
    group_hit, group_seen = Counter(), Counter()
    for r in rows:
        label_path = os.path.join(root, "labels", f"{r['id']}.json")
        if not os.path.exists(label_path):
            continue
        label = json.load(open(label_path, encoding="utf-8"))
        try:
            doc = parse_document(os.path.join(root, "samples", r["filename"]), r["kind"])
        except PipelineError as exc:
            print("PARSE FAIL", r["id"], exc)
            continue
        if label.get("invoice_count", 1) > 1:
            parts = [(inv, [p for p in doc.pages if inv["page_start"] <= p.page_no <= inv["page_end"]]) for inv in label["invoices"]]
            group = "multi"
        else:
            parts = [(label, doc.pages)]
            group = "receipt" if "receipt" in r["layout"] else (r["quality"] if r["quality"] != "digital" else "digital")
        for truth, pages in parts:
            res = ground_result(extract_by_rules(pages), pages)
            for f in FIELDS:
                want = norm(f, truth[f]["value"])
                got = norm(f, getattr(res, f).value)
                seen[f] += 1
                group_seen[group] += 1
                if want == got:
                    hit[f] += 1
                    group_hit[group] += 1
                elif verbose:
                    print(f"  {r['id']} {r['layout']:<28} {f:<15} want={want!r} got={got!r}")
    n = len(rows)
    print(f"\nsplit={split} docs={n}")
    for f in FIELDS:
        print(f"  {f:<15} {hit[f]:>3}/{seen[f]:<3} {100 * hit[f] / max(1, seen[f]):5.1f}%")
    for g in sorted(group_seen):
        print(f"  [{g:<8}] {group_hit[g]:>4}/{group_seen[g]:<4} {100 * group_hit[g] / group_seen[g]:5.1f}%")
    tot = sum(hit.values()), sum(seen.values())
    print(f"  {'ALL':<15} {tot[0]:>3}/{tot[1]:<3} {100 * tot[0] / max(1, tot[1]):5.1f}%")


if __name__ == "__main__":
    main()
