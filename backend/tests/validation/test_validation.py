"""Validation rules, duplicates and cross-checks."""
from __future__ import annotations

import datetime as dt
import time
from decimal import Decimal

from app.contracts import (
    CrosscheckKind,
    ExtractedField,
    ExtractedLineItem,
    ExtractionResult,
    IssueCode,
    IssueSeverity,
    LedgerRow,
    PageMethod,
    ParsedPage,
)
from app.validation import (
    ExistingInvoice,
    InMemoryDuplicateLookup,
    crosscheck,
    crosscheck_batch,
    crosscheck_issues,
    needs_review,
    normalize_supplier,
    validate_invoice,
)
from app.validation.checks import check_sanity

PAGE = [ParsedPage(page_no=1, text="x", method=PageMethod.TEXT_LAYER)]


def F(value, conf=0.9):
    return ExtractedField(value=value, confidence=conf if value is not None else 0, evidence=value if value is not None else None, page=1 if value is not None else None)


def make(**over):
    base = dict(
        invoice_number="INV-1", invoice_date="2026-03-14", supplier_name="Acme Widgets Ltd", customer_name="Globex",
        subtotal="100.00", tax="20.00", total="120.00", currency="EUR",
    )
    lines = over.pop("lines", [("Widget", "2", "50.00", "100.00")])
    notes = over.pop("notes", [])
    confs = over.pop("confs", {})
    base.update(over)
    fields = {k: F(v, confs.get(k, 0.9)) for k, v in base.items()}
    items = [ExtractedLineItem(description=d, quantity=q, unit_price=p, amount=a, confidence=0.9) for d, q, p, a in lines]
    return ExtractionResult(**fields, line_items=items, method="rules", notes=notes)


def codes(issues):
    return sorted((i.code.value if hasattr(i.code, "value") else i.code, i.severity.value if hasattr(i.severity, "value") else i.severity) for i in issues)


def test_clean_invoice_has_no_issues():
    issues = validate_invoice(make(), PAGE, None)
    assert issues == []
    assert not needs_review(issues)


def test_missing_required_fields_are_errors():
    issues = validate_invoice(make(invoice_number=None, total=None, lines=[]), PAGE, None)
    missing = [i for i in issues if i.code == IssueCode.MISSING_FIELD]
    assert {i.field for i in missing} == {"invoice_number", "total"}
    assert all(i.severity == IssueSeverity.ERROR for i in missing)
    assert needs_review(issues)


def test_missing_customer_and_tax_are_info():
    issues = validate_invoice(make(customer_name=None, tax=None, total="100.00"), PAGE, None)
    assert codes(issues) == [("MISSING_FIELD", "info")]  # tax omitted: subtotal == total
    assert not needs_review(issues)
    issues = validate_invoice(make(tax=None, total="120.00"), PAGE, None)
    assert ("SUBTOTAL_TAX_TOTAL_MISMATCH", "error") in codes(issues)
    assert ("MISSING_FIELD", "info") in codes(issues)


def test_rounding_within_tolerance_ok():
    issues = validate_invoice(make(subtotal="100.01", total="120.02", lines=[("w", "3", "33.34", "100.02")]), PAGE, None)
    assert issues == []


def test_line_items_subtotal_mismatch():
    issues = validate_invoice(make(lines=[("a", "1", "40", "40"), ("b", "1", "50", "50")]), PAGE, None)
    assert ("LINE_ITEMS_SUBTOTAL_MISMATCH", "error") in codes(issues)
    issue = next(i for i in issues if i.code == IssueCode.LINE_ITEMS_SUBTOTAL_MISMATCH)
    assert issue.details["line_items_sum"] == "90" and issue.details["subtotal"] == "100.00"


def test_wrong_total():
    issues = validate_invoice(make(total="125.00"), PAGE, None)
    assert codes(issues) == [("SUBTOTAL_TAX_TOTAL_MISMATCH", "error")]


def test_line_qty_times_price_is_warning():
    issues = validate_invoice(make(lines=[("w", "2", "40.00", "100.00")]), PAGE, None)
    assert codes(issues) == [("LINE_ITEMS_SUBTOTAL_MISMATCH", "warning")]
    assert issues[0].field == "line_items[0]"


def test_negative_amounts():
    issues = validate_invoice(make(subtotal="-100.00", tax="-20.00", total="-120.00", lines=[("refund", "1", "-100.00", "-100.00")]), PAGE, None)
    neg = [i for i in issues if i.code == IssueCode.NEGATIVE_AMOUNT]
    assert {i.field for i in neg} == {"subtotal", "tax", "total", "line_items[0]"}


def test_dates():
    assert codes(validate_invoice(make(invoice_date="2026-02-30"), PAGE, None)) == [("INVALID_DATE", "error")]
    assert codes(validate_invoice(make(invoice_date="1999-12-31"), PAGE, None)) == [("INVALID_DATE", "warning")]
    future = make(invoice_date="2030-01-01")
    assert codes(check_sanity(future, today=dt.date(2026, 10, 30))) == [("INVALID_DATE", "warning")]


def test_quality_notes_and_confidence():
    pages = [ParsedPage(page_no=1, text="x", method=PageMethod.OCR, ocr_confidence=0.41)]
    ex = make(currency=None, notes=["CURRENCY_AMBIGUOUS", "EVIDENCE_NOT_FOUND:customer_name"], confs={"supplier_name": 0.5})
    got = codes(validate_invoice(ex, pages, None))
    assert ("CURRENCY_AMBIGUOUS", "error") in got
    assert ("EVIDENCE_NOT_FOUND", "warning") in got
    assert ("LOW_CONFIDENCE", "warning") in got
    assert ("LOW_OCR_CONFIDENCE", "warning") in got


def test_supplier_normalization():
    assert normalize_supplier("ACME Widgets, Ltd.") == "acme widgets"
    assert normalize_supplier("Müller GmbH") == "muller"
    assert normalize_supplier("Société Générale S.A.") == "societe generale"


def test_exact_duplicate_excluding_itself():
    me = ExistingInvoice("me", "Acme Widgets Ltd", "INV-1", Decimal("120.00"), "2026-03-14")
    other = ExistingInvoice("other", "ACME WIDGETS LIMITED", "inv-1", Decimal("120.00"), "2026-03-20")
    issues = validate_invoice(make(), PAGE, InMemoryDuplicateLookup([me, other], exclude_id="me"))
    dup = [i for i in issues if i.code == IssueCode.DUPLICATE_EXACT]
    assert len(dup) == 1 and dup[0].details["matches"] == ["other"]
    assert validate_invoice(make(), PAGE, InMemoryDuplicateLookup([me], exclude_id="me")) == []


def test_near_duplicate_with_supplier_typo():
    typo = ExistingInvoice("t1", "Acme Widgts Ltd", "INV-1", Decimal("120.00"), "2026-03-14")
    issues = validate_invoice(make(), PAGE, InMemoryDuplicateLookup([typo]))
    assert codes(issues) == [("DUPLICATE_FUZZY", "error")]


def test_fuzzy_duplicate_same_total_close_date():
    near = ExistingInvoice("t2", "Acme Widgets", "INV-999", Decimal("120.00"), "2026-03-16")
    far = ExistingInvoice("t3", "Acme Widgets", "INV-998", Decimal("120.00"), "2026-04-30")
    issues = validate_invoice(make(), PAGE, InMemoryDuplicateLookup([near, far]))
    assert issues[0].details["matches"] == ["t2"]


def test_different_supplier_is_not_duplicate():
    other = ExistingInvoice("x", "Globex Corporation", "INV-1", Decimal("120.00"), "2026-03-14")
    assert validate_invoice(make(), PAGE, InMemoryDuplicateLookup([other])) == []


# --------------------------------------------------------------------------- cross-checks


def _row(**kw):
    base = dict(sheet_name="Ledger", row_no=2, invoice_number="INV-1", supplier_name="Acme Widgets", total="120.00", subtotal="100.00", tax="20.00", invoice_date="2026-03-14", currency="EUR")
    base.update(kw)
    return LedgerRow(**base)


def test_crosscheck_pdf_excel_match_and_mismatch():
    assert crosscheck(make(), [_row()]).result == "MATCH"
    res = crosscheck(make(), [_row(total="121.00")])
    assert res.result == "MISMATCH" and "total" in res.details["differences"]
    issues = crosscheck_issues(res)
    assert issues[0].code == IssueCode.CROSS_EXCEL_MISMATCH and issues[0].severity == IssueSeverity.ERROR


def test_crosscheck_ledger_row_missing():
    res = crosscheck(make(), [_row(invoice_number="OTHER-9")])
    assert res.result == "NO_MATCH"
    assert crosscheck_issues(res)[0].code == IssueCode.CROSS_NO_MATCH


def test_crosscheck_pdf_pdf():
    res = crosscheck(make(), make(invoice_date="2026-03-15"))
    assert res.kind == CrosscheckKind.PDF_PDF and res.result == "MISMATCH"
    assert crosscheck_issues(res)[0].code == IssueCode.CROSS_PDF_MISMATCH


def test_crosscheck_batch_5000_rows_fast():
    rows = [_row(invoice_number=f"INV-{i}", row_no=i + 2, total=f"{i}.00", subtotal=None, tax=None) for i in range(5000)]
    lefts = [{"id": f"L{i}", "invoice_number": f"INV-{i}", "supplier_name": "Acme Widgets Ltd", "total": f"{i}.00"} for i in range(0, 5000, 2)]
    lefts.append({"id": "Lx", "invoice_number": "NOPE", "supplier_name": "Acme", "total": "1.00"})
    lefts[1]["total"] = "999999.00"
    start = time.perf_counter()
    out = crosscheck_batch("PDF_EXCEL", lefts, rows)
    assert time.perf_counter() - start < 1.0
    results = [r.result for r in out["results"]]
    assert results.count("MATCH") == 2499 and results.count("MISMATCH") == 1 and results.count("NO_MATCH") == 1
    assert len(out["unmatched_right"]) == 2500


def test_no_float_in_validation_package():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "validation"
    for path in root.glob("*.py"):
        assert not re.search(r"\bfloat\(", path.read_text(encoding="utf-8")), path


def test_image_read_values_force_review():
    ex = make(notes=["VISION_UNVERIFIED:invoice_number", "VISION_UNVERIFIED:total"], confs={"invoice_number": 0.55, "total": 0.55})
    issues = validate_invoice(ex, PAGE, None)
    errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
    assert len(errors) == 1 and errors[0].code == IssueCode.LOW_CONFIDENCE
    assert errors[0].details["fields"] == ["invoice_number", "total"]
    assert needs_review(issues)
    # Once a person corrected those fields the notes are gone and so is the error.
    assert not needs_review(validate_invoice(make(), PAGE, None))
