"""End-to-end evaluation through the real API and workers.

Uploads the labeled documents, waits for the background pipeline, then
compares results with ground truth. Nothing here is estimated: every number
comes from this run.

Run inside the api container (PowerShell on the host):
    docker compose exec api python -m evaluation.run_eval --split test --reset
    docker compose exec api python -m evaluation.run_eval --split all --reset --large

--reset empties the database first (duplicates from earlier runs would
otherwise change the results). Outputs go to EVAL_OUT (default /data/eval,
mounted to docs/eval): results-<name>.json (raw) and summary-<name>.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

API = os.getenv("EVAL_API", "http://127.0.0.1:8000/api")
DATA = Path(os.getenv("DATA_DIR", "/data/repo"))
OUT = Path(os.getenv("EVAL_OUT", "/data/eval"))
FIELDS = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency"]
MONEY = {"subtotal", "tax", "total"}
TERMINAL = {"COMPLETED", "NEEDS_REVIEW", "FAILED"}


def norm(field: str, v: Any) -> Any:
    if v is None or v == "":
        return None
    if field in MONEY:
        try:
            return Decimal(str(v)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return str(v)
    return " ".join(str(v).split()).lower().rstrip(".")


def client() -> httpx.Client:
    return httpx.Client(base_url=API, headers={"X-API-Key": os.environ["API_KEY"]}, timeout=600)


def reset_db() -> None:
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE documents, crosschecks, llm_cache RESTART IDENTITY CASCADE"))
    try:
        from app.jobs import redis_conn

        r = redis_conn()
        for key in r.scan_iter("api_rl:*"):
            r.delete(key)
    except Exception:  # noqa: BLE001
        pass


def upload(c: httpx.Client, paths: list[Path]) -> list[dict]:
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    r = c.post("/documents", files=files)
    r.raise_for_status()
    return r.json()


def wait_done(c: httpx.Client, ids: list[str], timeout_s: int) -> dict[str, dict]:
    deadline = time.time() + timeout_s
    pending = set(ids)
    docs: dict[str, dict] = {}
    while pending and time.time() < deadline:
        for doc_id in list(pending):
            d = c.get(f"/documents/{doc_id}").json()
            if d["status"] in TERMINAL:
                docs[doc_id] = d
                pending.discard(doc_id)
        if pending:
            time.sleep(2)
    for doc_id in pending:
        docs[doc_id] = c.get(f"/documents/{doc_id}").json()
    return docs


def doc_timing(c: httpx.Client, doc_id: str) -> dict[str, Any]:
    events = c.get(f"/documents/{doc_id}/events").json()["items"]
    stage_ms = defaultdict(int)
    for e in events:
        if e["event"] == "SUCCEEDED" and e["duration_ms"] is not None:
            stage_ms[e["stage"]] += e["duration_ms"]
    return {"stage_ms": dict(stage_ms), "processing_ms": sum(stage_ms.values()), "events": events}


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "max": None}
    v = sorted(values)
    p95 = v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]
    return {"n": len(v), "mean": round(statistics.mean(v), 1), "p50": round(statistics.median(v), 1), "p95": round(p95, 1), "max": round(v[-1], 1)}


def group_of(row: dict) -> str:
    if row["expected_status"] == "FAILED":
        return "failure_file"
    if row["kind"] == "spreadsheet":
        return "spreadsheet"
    if "receipt" in row["layout"]:
        return "receipt_scan" if row["kind"] == "image" else "receipt"
    if row["layout"] == "multi_mixed":
        return "multi_invoice"
    return f"scan_{row['quality']}" if row["quality"] != "digital" else "digital"


def compare_fields(truth: dict, inv: dict | None, acc: dict, group: str, misses: list, doc_id: str) -> bool:
    all_ok = True
    for f in FIELDS:
        want = norm(f, truth[f]["value"])
        got = norm(f, inv.get(f)) if inv else None
        ok = want == got
        acc["field"][f][0] += ok
        acc["field"][f][1] += 1
        acc["group"][group][0] += ok
        acc["group"][group][1] += 1
        if not ok:
            all_ok = False
            misses.append({"doc": doc_id, "field": f, "want": str(want) if want is not None else None, "got": str(got) if got is not None else None})
    return all_ok


def evaluate(split: str, reset: bool, large: bool, timeout_s: int, name: str) -> dict[str, Any]:
    rows = list(csv.DictReader(open(DATA / "manifest.csv", encoding="utf-8")))
    if split != "all":
        rows = [r for r in rows if r["split"] == split]
    rows.sort(key=lambda r: r["id"])
    c = client()
    if reset:
        reset_db()
    stats_before = c.get("/stats").json()

    # 1. Upload in manifest order (batches of 20), as a user would.
    t0 = time.time()
    uploaded: dict[str, dict] = {}
    for i in range(0, len(rows), 20):
        batch = rows[i:i + 20]
        for row, res in zip(batch, upload(c, [DATA / "samples" / r["filename"] for r in batch])):
            uploaded[row["id"]] = res
    upload_s = time.time() - t0
    docs = wait_done(c, [u["id"] for u in uploaded.values()], timeout_s)
    wall_s = time.time() - t0

    acc = {"field": defaultdict(lambda: [0, 0]), "group": defaultdict(lambda: [0, 0])}
    misses: list[dict] = []
    status_rows, timing_rows = [], []
    llm_invoices = total_invoices = 0
    seeded, clean = [], []
    seg = {"true": 0, "found": 0, "correct": 0}
    ledger_docs = []

    for row in rows:
        up = uploaded[row["id"]]
        doc = docs[up["id"]]
        label = json.load(open(DATA / "labels" / f"{row['id']}.json", encoding="utf-8"))
        group = group_of(row)
        status_rows.append({"id": row["id"], "group": group, "expected": row["expected_status"], "actual": doc["status"],
                            "expected_code": row["expected_error_code"] or None, "actual_code": doc.get("error_code"),
                            "notes": row["notes"]})
        timing = doc_timing(c, up["id"]) if doc["status"] != "FAILED" or doc.get("page_count") else {"processing_ms": None, "stage_ms": {}}
        pages = doc.get("page_count") or 0
        if timing["processing_ms"] is not None and doc["status"] in ("COMPLETED", "NEEDS_REVIEW"):
            timing_rows.append({"id": row["id"], "group": group, "kind": row["kind"], "pages": pages, **{k: v for k, v in timing.items() if k != "events"}})
        if row["expected_status"] == "FAILED" or row["kind"] == "spreadsheet":
            if row["kind"] == "spreadsheet":
                ledger_docs.append((row, up["id"], label))
            continue

        invoices = [c.get(f"/invoices/{i['id']}").json() for i in doc.get("invoices", [])]
        total_invoices += len(invoices)
        llm_invoices += sum(1 for i in invoices if (i.get("extraction_method") or "").startswith("llm"))
        has_error = any(iss["severity"] == "error" and not iss["resolved"] for i in invoices for iss in i["issues"])
        error_codes = sorted({iss["code"] for i in invoices for iss in i["issues"] if iss["severity"] == "error"})
        if label.get("invoice_count", 1) > 1:
            truth_starts = {t["page_start"]: t for t in label["invoices"]}
            found = {i["page_start"]: i for i in invoices}
            seg["true"] += len(truth_starts)
            seg["found"] += len(found)
            seg["correct"] += sum(1 for s, i in found.items() if s in truth_starts and truth_starts[s]["page_end"] == i["page_end"])
            fields_ok = all([compare_fields(truth, found.get(start), acc, group, misses, f"{row['id']}@p{start}")
                             for start, truth in truth_starts.items()])
        else:
            fields_ok = compare_fields(label, invoices[0] if invoices else None, acc, group, misses, row["id"])
        entry = {"id": row["id"], "group": group, "notes": row["notes"], "flagged": has_error, "error_codes": error_codes,
                 "extraction_correct": fields_ok}
        (seeded if row["expected_status"] == "NEEDS_REVIEW" else clean).append(entry)

    # 2. PDF-vs-Excel cross-checks for every ledger.
    cross = {"rows": 0, "correct": 0, "details": []}
    for row, doc_id, label in ledger_docs:
        r = c.post("/crosschecks/run", json={"kind": "PDF_EXCEL", "right_ids": [doc_id]}).json()
        got = {it["left_ref"].get("invoice_number"): it["result"] for it in r.get("items", []) if it["result"] != "NO_MATCH"}
        for number, expected in label.get("crosscheck_expected", {}).items():
            cross["rows"] += 1
            ok = got.get(number) == expected
            cross["correct"] += ok
            if not ok:
                cross["details"].append({"ledger": row["id"], "invoice_number": number, "expected": expected, "got": got.get(number)})
        ledger_rows = c.get(f"/documents/{doc_id}/ledger", params={"limit": 1000}).json()["total"]
        cross["details"].append({"ledger": row["id"], "rows_parsed": ledger_rows, "rows_expected": len(label.get("ledger_rows", [])),
                                 "unmatched_right": r.get("unmatched_right_count")})

    stats_after = c.get("/stats").json()
    result = {
        "name": name, "split": split, "documents": len(rows), "upload_seconds": round(upload_s, 1), "wall_seconds": round(wall_s, 1),
        "llm_fake": os.getenv("LLM_FAKE", ""), "llm_models": [os.getenv("LLM_PRIMARY_MODEL"), os.getenv("LLM_FALLBACK_MODEL")],
        "field_accuracy": {f: {"correct": a, "total": b, "pct": pct(a, b)} for f, (a, b) in acc["field"].items()},
        "group_accuracy": {g: {"correct": a, "total": b, "pct": pct(a, b)} for g, (a, b) in sorted(acc["group"].items())},
        "overall_field_accuracy": pct(sum(a for a, _ in acc["field"].values()), sum(b for _, b in acc["field"].values())),
        "status": status_rows,
        "status_agreement": pct(sum(r["expected"] == r["actual"] for r in status_rows), len(status_rows)),
        "failure_code_agreement": pct(sum(r["expected_code"] == r["actual_code"] for r in status_rows if r["expected"] == "FAILED"),
                                      sum(1 for r in status_rows if r["expected"] == "FAILED")),
        "success_rate": pct(sum(r["actual"] in ("COMPLETED", "NEEDS_REVIEW") for r in status_rows if r["expected"] != "FAILED"),
                            sum(1 for r in status_rows if r["expected"] != "FAILED")),
        "unexpected_failure_rate": pct(sum(r["actual"] == "FAILED" for r in status_rows if r["expected"] != "FAILED"),
                                       sum(1 for r in status_rows if r["expected"] != "FAILED")),
        "failure_rate_all": pct(sum(r["actual"] == "FAILED" for r in status_rows), len(status_rows)),
        "llm_share": {"llm_invoices": llm_invoices, "invoices": total_invoices, "pct": pct(llm_invoices, total_invoices)},
        "validation": {
            "seeded_recall": {"flagged": sum(s["flagged"] for s in seeded), "seeded": len(seeded), "pct": pct(sum(s["flagged"] for s in seeded), len(seeded))},
            "clean_false_positive": {"flagged": sum(s["flagged"] for s in clean), "clean": len(clean), "pct": pct(sum(s["flagged"] for s in clean), len(clean))},
            # The validator's own mistakes: clean documents flagged although every field was extracted correctly.
            "validator_false_positive": {"flagged": sum(s["flagged"] for s in clean if s["extraction_correct"]),
                                         "clean_and_correct": sum(1 for s in clean if s["extraction_correct"]),
                                         "pct": pct(sum(s["flagged"] for s in clean if s["extraction_correct"]),
                                                    sum(1 for s in clean if s["extraction_correct"]))},
            "seeded_detail": seeded, "clean_flagged": [s for s in clean if s["flagged"]],
        },
        "segmentation": {**seg, "precision": pct(seg["correct"], seg["found"]), "recall": pct(seg["correct"], seg["true"])},
        "crosscheck": {**cross, "accuracy": pct(cross["correct"], cross["rows"])},
        "timing": {
            "per_document_ms": quantiles([t["processing_ms"] for t in timing_rows]),
            "per_page_ms": quantiles([t["processing_ms"] / t["pages"] for t in timing_rows if t["pages"]]),
            "by_group_ms": {g: quantiles([t["processing_ms"] for t in timing_rows if t["group"] == g]) for g in sorted({t["group"] for t in timing_rows})},
            "rows": timing_rows,
        },
        "field_misses": misses,
        "stats_api": stats_after,
        "stats_before": stats_before,
    }
    if large:
        result["large"] = evaluate_large(c, timeout_s)
    return result


def evaluate_large(c: httpx.Client, timeout_s: int) -> dict[str, Any]:
    path = DATA / "samples_large" / "multi_1000.pdf"
    label_path = DATA / "samples_large" / "multi_1000.json"
    if not path.exists():
        return {"skipped": "data/samples_large/multi_1000.pdf not found; run tools/datagen/generate.py --large"}
    label = json.load(open(label_path, encoding="utf-8"))
    t0 = time.time()
    res = upload(c, [path])[0]
    doc = wait_done(c, [res["id"]], timeout_s)[res["id"]]
    wall = time.time() - t0
    timing = doc_timing(c, res["id"])
    detail = c.get(f"/documents/{res['id']}").json()
    found = {i["page_start"]: i for i in detail.get("invoices", [])}
    truth = {t["page_start"]: t for t in label["invoices"]}
    correct = sum(1 for s, i in found.items() if s in truth and truth[s]["page_end"] == i["page_end"])
    acc = {"field": defaultdict(lambda: [0, 0]), "group": defaultdict(lambda: [0, 0])}
    for start, t in truth.items():
        compare_fields(t, found.get(start), acc, "large", [], f"large@p{start}")
    pages = detail.get("page_count") or label["page_count"]
    return {
        "status": doc["status"], "error_code": doc.get("error_code"), "pages": pages, "invoices_true": len(truth),
        "invoices_found": len(found), "segmentation_precision": pct(correct, len(found)), "segmentation_recall": pct(correct, len(truth)),
        "wall_seconds": round(wall, 1), "stage_ms": timing["stage_ms"], "processing_ms": timing["processing_ms"],
        "pages_per_second": round(pages / (timing["processing_ms"] / 1000), 2) if timing["processing_ms"] else None,
        "field_accuracy": {f: {"correct": a, "total": b, "pct": pct(a, b)} for f, (a, b) in acc["field"].items()},
        "overall_field_accuracy": pct(sum(a for a, _ in acc["field"].values()), sum(b for _, b in acc["field"].values())),
        "scanned_invoices": len(label.get("scanned_invoices", [])),
    }


def summary_md(r: dict) -> str:
    def t(rows: list[list[Any]], head: list[str]) -> str:
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        out += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
        return "\n".join(out)

    lines = [f"## Run `{r['name']}` (split: {r['split']}, {r['documents']} documents, LLM_FAKE={r['llm_fake']})", ""]
    lines += ["### Field accuracy (pipeline output vs labels)", "",
              t([[f, v["correct"], v["total"], f"{v['pct']}%"] for f, v in r["field_accuracy"].items()], ["Field", "Correct", "Total", "Accuracy"]),
              "", f"Overall: **{r['overall_field_accuracy']}%**", "",
              t([[g, v["correct"], v["total"], f"{v['pct']}%"] for g, v in r["group_accuracy"].items()], ["Document group", "Correct", "Total", "Accuracy"]), ""]
    v = r["validation"]
    lines += ["### Outcomes", "",
              t([["Status matches expected", f"{r['status_agreement']}%"],
                 ["Success rate (expected-good files that finished)", f"{r['success_rate']}%"],
                 ["Unexpected failure rate", f"{r['unexpected_failure_rate']}%"],
                 ["Failure files with the expected error code", f"{r['failure_code_agreement']}%"],
                 ["Invoices that needed an LLM call", f"{r['llm_share']['llm_invoices']}/{r['llm_share']['invoices']} = {r['llm_share']['pct']}%"],
                 ["Seeded errors flagged (recall)", f"{v['seeded_recall']['flagged']}/{v['seeded_recall']['seeded']} = {v['seeded_recall']['pct']}%"],
                 ["Clean documents sent to review (end to end)", f"{v['clean_false_positive']['flagged']}/{v['clean_false_positive']['clean']} = {v['clean_false_positive']['pct']}%"],
                 ["Validator false positives (clean and correctly extracted, still flagged)",
                  f"{v['validator_false_positive']['flagged']}/{v['validator_false_positive']['clean_and_correct']} = {v['validator_false_positive']['pct']}%"],
                 ["Segmentation precision / recall", f"{r['segmentation']['precision']}% / {r['segmentation']['recall']}%"],
                 ["PDF-vs-Excel cross-check accuracy", f"{r['crosscheck']['correct']}/{r['crosscheck']['rows']} = {r['crosscheck']['accuracy']}%"],
                 ["Wall time (upload to last result)", f"{r['wall_seconds']} s"]], ["Metric", "Value"]), ""]
    tm = r["timing"]
    lines += ["### Processing time (sum of stage durations)", "",
              t([[k, q["n"], q["mean"], q["p50"], q["p95"], q["max"]] for k, q in [("per document (ms)", tm["per_document_ms"]), ("per page (ms)", tm["per_page_ms"])]
                 + [(f"{g} (ms/doc)", q) for g, q in tm["by_group_ms"].items()]], ["Measure", "n", "mean", "p50", "p95", "max"]), ""]
    if r.get("large") and "pages" in r["large"]:
        lg = r["large"]
        lines += ["### 1,000-page PDF", "",
                  t([["Status", lg["status"]], ["Pages", lg["pages"]], ["Invoices (true / found)", f"{lg['invoices_true']} / {lg['invoices_found']}"],
                     ["Segmentation precision / recall", f"{lg['segmentation_precision']}% / {lg['segmentation_recall']}%"],
                     ["Processing time", f"{round(lg['processing_ms'] / 1000, 1)} s ({lg['pages_per_second']} pages/s)"],
                     ["Stage time (s)", ", ".join(f"{k} {round(v / 1000, 1)}" for k, v in lg["stage_ms"].items())],
                     ["Field accuracy over all invoices", f"{lg['overall_field_accuracy']}%"]], ["Metric", "Value"]), ""]
    mism = [s for s in r["status"] if s["expected"] != s["actual"] or (s["expected"] == "FAILED" and s["expected_code"] != s["actual_code"])]
    if mism:
        lines += ["### Documents whose status differed from expected", "",
                  t([[s["id"], s["group"], s["expected"], s["actual"], s["expected_code"], s["actual_code"], s["notes"]] for s in mism],
                    ["Doc", "Group", "Expected", "Actual", "Exp. code", "Actual code", "Notes"]), ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    ap.add_argument("--reset", action="store_true", help="empty the database first")
    ap.add_argument("--large", action="store_true", help="also process data/samples_large/multi_1000.pdf")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--name", default=None)
    a = ap.parse_args()
    name = a.name or a.split
    result = evaluate(a.split, a.reset, a.large, a.timeout, name)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"results-{name}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    md = summary_md(result)
    (OUT / f"summary-{name}.md").write_text(md + "\n", encoding="utf-8")
    print(md)


if __name__ == "__main__":
    sys.exit(main())
