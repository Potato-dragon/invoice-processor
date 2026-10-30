"""API + pipeline tests against a real Postgres test database (pipeline runs inline)."""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from unittest.mock import patch

import pymupdf
import pytest

from app.contracts import ErrorCode, PipelineError

pytestmark = pytest.mark.usefixtures("test_db")


@pytest.fixture(scope="module")
def client(test_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.headers["X-API-Key"] = os.environ["API_KEY"]
        yield c


def amounts(number: str, extra: str = "0") -> tuple[str, str, str]:
    """Unique amounts per invoice number, so unrelated test invoices never look like duplicates."""
    sub = Decimal(100 + int(number[-6:], 16) % 9000)
    tax = (sub / 10).quantize(Decimal("0.01"))
    return f"{sub:.2f}", f"{tax:.2f}", f"{sub + tax + Decimal(extra):.2f}"


def invoice_pdf(number: str, total_extra: str = "0", supplier: str = "Apex Test Supplies Ltd") -> bytes:
    subtotal, tax, total = amounts(number, total_extra)
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        supplier, "12 Test Street, Springfield", "", "INVOICE", f"Invoice Number: {number}", "Invoice Date: 2026-01-15",
        "Bill To: Beacon Testing Inc.", "", "Description Qty Unit Price Amount",
        f"Consulting hours 1 {subtotal} {subtotal}", "", f"Subtotal: USD {subtotal}", f"Tax (10%): USD {tax}", f"Total: USD {total}",
    ]
    page.insert_text((60, 60), "\n".join(lines), fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def upload(client, *files):
    r = client.post("/api/documents", files=[("files", f) for f in files])
    assert r.status_code == 201, r.text
    return r.json()


def num() -> str:
    return f"INV-T{uuid.uuid4().hex[:6].upper()}"


# --------------------------------------------------------------------------- auth + errors


def test_health_needs_no_key(client):
    r = client.get("/api/health", headers={"X-API-Key": ""})
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_missing_key_is_unauthorized(client):
    r = client.get("/api/documents", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "UNAUTHORIZED", "message": "missing or wrong X-API-Key header"}}


def test_not_found_uses_error_body(client):
    r = client.get(f"/api/documents/{uuid.uuid4()}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    r = client.get("/api/invoices/not-a-uuid")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- upload + pipeline


def test_pdf_and_csv_complete_with_four_stage_events(client):
    n = num()
    total = amounts(n)[2]
    csv = f"Invoice No,Date,Supplier,Total\n{n},2026-01-15,Apex Test Supplies Ltd,{total}\n".encode()
    res = upload(client, ("a.pdf", invoice_pdf(n), "application/pdf"), ("ledger.csv", csv, "text/csv"))
    assert [r["status"] for r in res] == ["COMPLETED", "COMPLETED"], res

    pdf_doc = client.get(f"/api/documents/{res[0]['id']}").json()
    assert pdf_doc["page_count"] == 1 and len(pdf_doc["invoices"]) == 1
    inv = client.get(f"/api/invoices/{pdf_doc['invoices'][0]['id']}").json()
    assert inv["invoice_number"] == n and inv["total"] == total and inv["currency"] == "USD"
    assert inv["review_status"] == "AUTO_OK" and inv["extraction_method"] == "rules"
    assert inv["extraction"]["total"]["evidence"]

    events = client.get(f"/api/documents/{res[0]['id']}/events").json()["items"]
    ok = [e["stage"] for e in events if e["event"] == "SUCCEEDED"]
    assert ok == ["parse", "extract", "validate", "index"]
    assert all(e["duration_ms"] is not None for e in events if e["event"] == "SUCCEEDED")

    ledger = client.get(f"/api/documents/{res[1]['id']}/ledger").json()
    assert ledger["total"] == 1 and ledger["items"][0]["total"] == total


def test_batch_with_bad_files_does_not_fail_others(client):
    res = upload(client,
                 ("good.pdf", invoice_pdf(num()), "application/pdf"),
                 ("notes.docx", b"PK\x03\x04garbage", "application/octet-stream"),
                 ("empty.pdf", b"", "application/pdf"),
                 ("fake.pdf", b"hello, I am text", "application/pdf"))
    assert res[0]["status"] == "COMPLETED"
    assert [r["error"]["code"] for r in res[1:]] == ["FILE_TYPE_UNSUPPORTED", "FILE_EMPTY", "FILE_TYPE_UNSUPPORTED"]
    failed = client.get(f"/api/documents/{res[2]['id']}").json()
    assert failed["status"] == "FAILED" and failed["error_code"] == "FILE_EMPTY"


def test_oversize_file(client):
    from app.config import get_settings

    with patch.object(get_settings(), "max_upload_mb", 1):
        res = upload(client, ("big.pdf", b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10), "application/pdf"))
    assert res[0]["error"]["code"] == "FILE_TOO_LARGE"


def test_corrupt_pdf_fails_in_parse_with_code(client):
    data = invoice_pdf(num())
    res = upload(client, ("broken.pdf", data[:60], "application/pdf"))
    doc = client.get(f"/api/documents/{res[0]['id']}").json()
    assert doc["status"] == "FAILED" and doc["error_code"] == "FILE_CORRUPT" and doc["current_stage"] == "parse"


def test_stage_failure_then_reprocess(client):
    calls = {"n": 0}
    real = __import__("app.parsing", fromlist=["parse_document"]).parse_document

    def flaky(path, kind):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PipelineError(ErrorCode.OCR_FAILED, "simulated OCR crash")
        return real(path, kind)

    with patch("app.parsing.parse_document", side_effect=flaky):
        res = upload(client, ("x.pdf", invoice_pdf(num()), "application/pdf"))
        doc = client.get(f"/api/documents/{res[0]['id']}").json()
        assert doc["status"] == "FAILED" and doc["error_code"] == "OCR_FAILED"
        r = client.post(f"/api/documents/{res[0]['id']}/reprocess")
        assert r.status_code == 202 and r.json()["reprocess_from"] == "parse"
    doc = client.get(f"/api/documents/{res[0]['id']}").json()
    assert doc["status"] == "COMPLETED" and doc["error_code"] is None
    kinds = [e["event"] for e in client.get(f"/api/documents/{res[0]['id']}/events").json()["items"]]
    assert "FAILED" in kinds and "RETRIED" in kinds and kinds[-1] == "SUCCEEDED"


def test_unexpected_error_becomes_internal_error(client):
    from app import pipeline

    with patch.dict(pipeline.STAGES, {pipeline.Stage.INDEX: lambda s, d: (_ for _ in ()).throw(RuntimeError("boom"))}):
        res = upload(client, ("y.pdf", invoice_pdf(num()), "application/pdf"))
    doc = client.get(f"/api/documents/{res[0]['id']}").json()
    assert doc["status"] == "FAILED" and doc["error_code"] == "INTERNAL_ERROR" and doc["current_stage"] == "index"
    assert client.post(f"/api/documents/{res[0]['id']}/reprocess").json()["reprocess_from"] == "index"
    assert client.get(f"/api/documents/{res[0]['id']}").json()["status"] == "COMPLETED"


def test_rerunning_stages_does_not_duplicate_rows(client):
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Invoice, InvoiceLineItem, Page, ValidationIssue

    res = upload(client, ("z.pdf", invoice_pdf(num(), total_extra="5.00"), "application/pdf"))
    doc_id = uuid.UUID(res[0]["id"])

    def counts():
        with SessionLocal() as s:
            inv_ids = select(Invoice.id).where(Invoice.document_id == doc_id)
            return (s.execute(select(func.count()).where(Page.document_id == doc_id)).scalar(),
                    s.execute(select(func.count()).where(Invoice.document_id == doc_id)).scalar(),
                    s.execute(select(func.count()).where(InvoiceLineItem.invoice_id.in_(inv_ids))).scalar(),
                    s.execute(select(func.count()).where(ValidationIssue.document_id == doc_id)).scalar())

    before = counts()
    assert before[3] >= 1  # the wrong total is flagged
    for stage in ("parse", "extract", "validate"):
        assert client.post(f"/api/documents/{doc_id}/reprocess?from={stage}").status_code == 202
        assert counts() == before


# --------------------------------------------------------------------------- review flow


def test_wrong_total_needs_review_then_correction_clears_it(client):
    n = num()
    res = upload(client, ("w.pdf", invoice_pdf(n, total_extra="2.50"), "application/pdf"))
    doc = client.get(f"/api/documents/{res[0]['id']}").json()
    assert doc["status"] == "NEEDS_REVIEW"
    inv_id = doc["invoices"][0]["id"]
    inv = client.get(f"/api/invoices/{inv_id}").json()
    assert "SUBTOTAL_TAX_TOTAL_MISMATCH" in [i["code"] for i in inv["issues"]]

    bad = client.patch(f"/api/invoices/{inv_id}", json={"total": "abc"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "BAD_REQUEST"
    assert client.patch(f"/api/invoices/{inv_id}", json={"colour": "red"}).status_code == 400

    right, wrong = amounts(n)[2], amounts(n, "2.50")[2]
    fixed = client.patch(f"/api/invoices/{inv_id}", json={"total": right}).json()
    assert fixed["review_status"] == "CORRECTED" and fixed["total"] == right
    assert fixed["corrections"][-1] == {**fixed["corrections"][-1], "field": "total", "old_value": wrong, "new_value": right}
    assert not [i for i in fixed["issues"] if i["severity"] == "error"]
    assert client.get(f"/api/documents/{res[0]['id']}").json()["status"] == "COMPLETED"


def test_exact_duplicate_is_flagged_and_can_be_resolved(client):
    n = num()
    first = upload(client, ("d1.pdf", invoice_pdf(n), "application/pdf"))
    second = upload(client, ("d2.pdf", invoice_pdf(n) + b"\n", "application/pdf"))
    assert client.get(f"/api/documents/{first[0]['id']}").json()["status"] == "COMPLETED"
    doc2 = client.get(f"/api/documents/{second[0]['id']}").json()
    assert doc2["status"] == "NEEDS_REVIEW"
    inv = client.get(f"/api/invoices/{doc2['invoices'][0]['id']}").json()
    dup = next(i for i in inv["issues"] if i["code"] == "DUPLICATE_EXACT")
    r = client.post(f"/api/issues/{dup['id']}/resolve", json={"resolved": True})
    assert r.status_code == 200 and r.json()["resolved"] is True
    assert client.get(f"/api/invoices/{inv['id']}").json()["review_status"] == "AUTO_OK"
    issues = client.get("/api/issues", params={"code": "DUPLICATE_EXACT", "resolved": "true"}).json()
    assert any(i["id"] == dup["id"] for i in issues["items"])


# --------------------------------------------------------------------------- search + crosschecks + stats


def test_search_modes_and_filters(client):
    n = num()
    upload(client, ("s.pdf", invoice_pdf(n, supplier="Zephyr Quantum Robotics Ltd"), "application/pdf"))
    for mode in ("keyword", "semantic", "hybrid"):
        r = client.get("/api/search", params={"q": "Zephyr Quantum Robotics", "mode": mode})
        assert r.status_code == 200, r.text
        assert r.json()["items"][0]["supplier_name"] == "Zephyr Quantum Robotics Ltd", mode
    by_number = client.get("/api/search", params={"q": n, "mode": "keyword"}).json()
    assert by_number["items"][0]["invoice_number"] == n
    semantic = client.get("/api/search", params={"q": "robot automation company invoice", "mode": "semantic"}).json()
    assert any(i["supplier_name"] == "Zephyr Quantum Robotics Ltd" for i in semantic["items"][:5])
    filt = client.get("/api/search", params={"supplier": "zephyr", "currency": "usd", "min_total": "100", "max_total": "20000"}).json()
    assert filt["total"] >= 1 and all(i["currency"] == "USD" for i in filt["items"])
    assert client.get("/api/search", params={"q": "x", "mode": "magic"}).status_code == 400


def test_crosscheck_pdf_vs_excel(client):
    n_ok, n_bad, n_missing = num(), num(), num()
    pdfs = upload(client, ("c1.pdf", invoice_pdf(n_ok), "application/pdf"), ("c2.pdf", invoice_pdf(n_bad), "application/pdf"),
                  ("c3.pdf", invoice_pdf(n_missing), "application/pdf"))
    ok_total = amounts(n_ok)[2].replace(".", ",")
    csv = (f"Invoice No;Supplier;Total\n{n_ok};Apex Test Supplies Ltd;{ok_total}\n{n_bad};Apex Test Supplies;1,00\n"
           f"EXTRA-1;Someone Else;10,00\n").encode()
    sheet = upload(client, ("ledger.csv", csv, "text/csv"))[0]
    left = [client.get(f"/api/documents/{p['id']}").json()["invoices"][0]["id"] for p in pdfs]
    r = client.post("/api/crosschecks/run", json={"kind": "PDF_EXCEL", "left_ids": left, "right_ids": [sheet["id"]]})
    assert r.status_code == 202
    body = r.json()
    assert body["summary"] == {"MATCH": 1, "MISMATCH": 1, "NO_MATCH": 1}
    assert body["unmatched_right_count"] == 1
    bad = client.get(f"/api/invoices/{left[1]}").json()
    assert "CROSS_EXCEL_MISMATCH" in [i["code"] for i in bad["issues"]] and bad["review_status"] == "NEEDS_REVIEW"
    # Re-running does not stack duplicate cross-check issues.
    client.post("/api/crosschecks/run", json={"kind": "PDF_EXCEL", "left_ids": left, "right_ids": [sheet["id"]]})
    again = client.get(f"/api/invoices/{left[1]}").json()
    assert [i["code"] for i in again["issues"]].count("CROSS_EXCEL_MISMATCH") == 1
    assert client.get("/api/crosschecks", params={"result": "MISMATCH"}).json()["total"] >= 1


def test_stats(client):
    s = client.get("/api/stats").json()
    assert s["documents"]["total"] > 0 and "parse" in s["stages"]
    assert 0 <= s["documents"]["failure_rate"] <= 1
