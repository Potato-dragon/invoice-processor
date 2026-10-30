"""Parsing tests. Fixtures are built in code; nothing here depends on data/."""
from __future__ import annotations

import io
import os
import time
from unittest.mock import patch

import pymupdf as fitz
import numpy as np
import pytest
from PIL import Image, ImageFilter

from app.contracts import ErrorCode, PageMethod, ParsedPage, PipelineError
from app.parsing import parse_document, segment_pages
from app.parsing.ocr import estimate_skew

INVOICE_TEXT = [
    "ACME Widgets Ltd",
    "INVOICE",
    "Invoice No: INV-{n}",
    "Date: 2026-03-14",
    "Bill To: Globex Corp",
    "Widget A    2 x 10.00    20.00",
    "Subtotal 20.00",
    "Tax 2.00",
    "Total 22.00",
]


def _text_pdf(path, n_invoices=1, pages_per_invoice=1, fontsize=11):
    doc = fitz.open()
    for i in range(n_invoices):
        for k in range(pages_per_invoice):
            page = doc.new_page()
            lines = [ln.format(n=1000 + i) for ln in INVOICE_TEXT]
            if pages_per_invoice > 1:
                lines.append(f"Page {k + 1} of {pages_per_invoice}")
            page.insert_text((72, 72), "\n".join(lines), fontsize=fontsize)
    doc.save(path)
    doc.close()
    return path


def _render_scan(angle=0.0, noise=0, blur=False, dpi=200):
    src = fitz.open()
    page = src.new_page()
    page.insert_text((72, 72), "\n".join(ln.format(n=4242) for ln in INVOICE_TEXT), fontsize=14)
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    src.close()
    if angle:
        img = img.rotate(angle, expand=True, fillcolor=255)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(0.8))
    if noise:
        arr = np.asarray(img).astype(np.int16)
        rng = np.random.default_rng(0)
        arr = np.clip(arr + rng.normal(0, noise, arr.shape), 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
    return img


def _image_pdf(path, img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=img.width * 72 / 200, height=img.height * 72 / 200)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return path


# --------------------------------------------------------------------------- PDF


def test_text_layer_pdf(tmp_path):
    doc = parse_document(_text_pdf(str(tmp_path / "a.pdf")), "pdf")
    assert len(doc.pages) == 1
    page = doc.pages[0]
    assert page.method == PageMethod.TEXT_LAYER and page.ocr_confidence is None
    assert "INV-1000" in page.text and page.width and page.height
    assert doc.invoice_ranges == [(1, 1)]


def test_scanned_pdf_uses_ocr(tmp_path):
    doc = parse_document(_image_pdf(str(tmp_path / "s.pdf"), _render_scan()), "pdf")
    page = doc.pages[0]
    assert page.method == PageMethod.OCR
    assert 0.5 < page.ocr_confidence <= 1
    assert "INV-4242" in page.text.replace(" ", "")
    assert "Total" in page.text


def test_rotated_noisy_scan_is_deskewed(tmp_path):
    img = _render_scan(angle=4, noise=25, blur=True)
    doc = parse_document(_image_pdf(str(tmp_path / "r.pdf"), img), "pdf")
    assert doc.pages[0].method == PageMethod.OCR
    assert "4242" in doc.pages[0].text
    assert "Total" in doc.pages[0].text


@pytest.mark.parametrize("angle", [-6, -3, 3, 5])
def test_skew_estimate_close_to_truth(angle):
    img = np.asarray(_render_scan(angle=angle))
    assert abs(abs(estimate_skew(img)) - abs(angle)) < 1.5


def test_corrupt_pdf(tmp_path):
    good = _text_pdf(str(tmp_path / "g.pdf"))
    data = open(good, "rb").read()
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(data[:40])
    with pytest.raises(PipelineError) as exc:
        parse_document(str(bad), "pdf")
    assert exc.value.code == ErrorCode.FILE_CORRUPT


def test_not_really_a_pdf(tmp_path):
    p = tmp_path / "fake.pdf"
    p.write_text("hello, I am a text file")
    with pytest.raises(PipelineError) as exc:
        parse_document(str(p), "pdf")
    assert exc.value.code == ErrorCode.FILE_CORRUPT


def test_encrypted_pdf(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "secret invoice")
    path = str(tmp_path / "enc.pdf")
    doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    with pytest.raises(PipelineError) as exc:
        parse_document(path, "pdf")
    assert exc.value.code == ErrorCode.FILE_ENCRYPTED


def test_empty_file(tmp_path):
    for kind, name in (("pdf", "e.pdf"), ("image", "e.png"), ("spreadsheet", "e.csv")):
        p = tmp_path / name
        p.write_bytes(b"")
        with pytest.raises(PipelineError) as exc:
            parse_document(str(p), kind)
        assert exc.value.code == ErrorCode.FILE_EMPTY


def test_page_limit(tmp_path):
    path = _text_pdf(str(tmp_path / "many.pdf"), n_invoices=5)
    with patch.dict(os.environ, {"MAX_PAGES": "3"}):
        with pytest.raises(PipelineError) as exc:
            parse_document(path, "pdf")
    assert exc.value.code == ErrorCode.PAGE_LIMIT_EXCEEDED


def test_blank_pdf_fails_with_ocr_failed(tmp_path):
    doc = fitz.open()
    doc.new_page()
    path = str(tmp_path / "blank.pdf")
    doc.save(path)
    doc.close()
    with pytest.raises(PipelineError) as exc:
        parse_document(path, "pdf")
    assert exc.value.code == ErrorCode.OCR_FAILED


def test_hundred_page_pdf_is_fast(tmp_path):
    path = _text_pdf(str(tmp_path / "big.pdf"), n_invoices=100)
    start = time.perf_counter()
    doc = parse_document(path, "pdf")
    elapsed = time.perf_counter() - start
    assert len(doc.pages) == 100
    assert len(doc.invoice_ranges) == 100
    assert elapsed < 10, f"100 pages took {elapsed:.1f}s"


# --------------------------------------------------------------------------- images


def test_png_and_jpg(tmp_path):
    img = _render_scan()
    for ext in ("png", "jpg"):
        p = str(tmp_path / f"i.{ext}")
        img.convert("RGB").save(p, quality=80) if ext == "jpg" else img.save(p)
        doc = parse_document(p, "image")
        assert doc.pages[0].method == PageMethod.OCR
        assert "Total" in doc.pages[0].text


def test_multiframe_tiff(tmp_path):
    frames = [_render_scan(), _render_scan(noise=10)]
    p = str(tmp_path / "m.tiff")
    frames[0].save(p, save_all=True, append_images=frames[1:], compression="tiff_lzw")
    doc = parse_document(p, "image")
    assert [pg.page_no for pg in doc.pages] == [1, 2]
    assert all(pg.method == PageMethod.OCR for pg in doc.pages)


def test_corrupt_image(tmp_path):
    p = tmp_path / "c.png"
    buf = io.BytesIO()
    _render_scan().save(buf, format="PNG")
    p.write_bytes(buf.getvalue()[:200])
    with pytest.raises(PipelineError) as exc:
        parse_document(str(p), "image")
    assert exc.value.code == ErrorCode.FILE_CORRUPT


# --------------------------------------------------------------------------- spreadsheets


def test_xlsx_junk_sheet_and_header_on_row_5(tmp_path):
    import openpyxl
    import datetime as dt

    wb = openpyxl.Workbook()
    junk = wb.active
    junk.title = "Notes"
    junk["A1"] = "This sheet has no table"
    ws = wb.create_sheet("Ledger")
    ws["A1"] = "Company ledger export"
    ws["A2"] = "Generated 2026-03-31"
    ws.append([])
    ws.append([])
    ws.append(["Invoice No", "Date", "Vendor", "Net", "VAT", "Total", "Currency"])  # row 5
    ws.append(["INV-1", dt.date(2026, 3, 1), "ACME Ltd", 100, 20, 120.5, "eur"])
    ws.append(["INV-2", "14/03/2026", "Globex", "1.234,56", "0", "1.234,56", "EUR"])
    ws.append([None, None, None, None, None, None, None])
    ws.append(["Total", None, None, None, None, 1355.06, None])
    wb.create_sheet("Empty")
    p = str(tmp_path / "l.xlsx")
    wb.save(p)

    doc = parse_document(p, "spreadsheet")
    assert doc.pages == [] and doc.invoice_ranges == []
    rows = doc.ledger_rows
    assert [r.invoice_number for r in rows] == ["INV-1", "INV-2"]
    assert rows[0].sheet_name == "Ledger" and rows[0].row_no == 6
    assert rows[0].invoice_date == "2026-03-01" and rows[0].total == "120.50" and rows[0].currency == "EUR"
    assert rows[1].total == "1234.56" and rows[1].invoice_date == "2026-03-14"
    assert rows[0].raw["Vendor"] == "ACME Ltd"
    assert any("Notes" in w for w in doc.warnings)


def test_spreadsheets_without_file_extension(tmp_path):
    """Uploads are stored under random keys with no extension."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.append(["Invoice No", "Supplier", "Total"])
    wb.active.append(["INV-9", "Acme", 10])
    p = tmp_path / "a" / "0f3c9e"
    p.parent.mkdir()
    wb.save(p)
    assert parse_document(str(p), "spreadsheet").ledger_rows[0].total == "10.00"


def test_semicolon_latin1_csv(tmp_path):
    content = "Numéro facture;Date facture;Fournisseur;Montant TTC\nF-001;14/03/2026;Société Générale;1 234,56 EUR\nF-002;15/03/2026;Café Dupont;99,90 EUR\n"
    p = tmp_path / "f.csv"
    p.write_bytes(content.encode("latin-1"))
    rows = parse_document(str(p), "spreadsheet").ledger_rows
    assert [r.invoice_number for r in rows] == ["F-001", "F-002"]
    assert rows[0].supplier_name == "Société Générale"
    assert rows[0].total == "1234.56" and rows[0].currency == "EUR"


def test_tab_and_pipe_csv(tmp_path):
    for delim in ("\t", "|"):
        p = tmp_path / "t.csv"
        p.write_text(delim.join(["Invoice #", "Supplier", "Amount"]) + "\n" + delim.join(["A-1", "Acme", "1,234.50"]) + "\n")
        rows = parse_document(str(p), "spreadsheet").ledger_rows
        assert rows[0].invoice_number == "A-1" and rows[0].total == "1234.50"


def test_legacy_xls(tmp_path):
    xlwt = pytest.importorskip("xlwt")
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Rechnungen")
    for c, h in enumerate(["Rechnungsnummer", "Datum", "Lieferant", "Summe"]):
        ws.write(0, c, h)
    for c, v in enumerate(["R-77", "01.03.2026", "Muster GmbH", 500.25]):
        ws.write(1, c, v)
    p = str(tmp_path / "old.xls")
    wb.save(p)
    rows = parse_document(p, "spreadsheet").ledger_rows
    assert rows[0].invoice_number == "R-77" and rows[0].total == "500.25" and rows[0].invoice_date == "2026-03-01"


def test_bad_spreadsheet(tmp_path):
    p = tmp_path / "x.xlsx"
    p.write_bytes(b"PK\x03\x04 this is not a real zip")
    with pytest.raises(PipelineError) as exc:
        parse_document(str(p), "spreadsheet")
    assert exc.value.code == ErrorCode.SPREADSHEET_PARSE_FAILED
    p2 = tmp_path / "nothing.csv"
    p2.write_text("just,some,words\n1,2,3\n")
    with pytest.raises(PipelineError) as exc:
        parse_document(str(p2), "spreadsheet")
    assert exc.value.code == ErrorCode.SPREADSHEET_PARSE_FAILED


# --------------------------------------------------------------------------- segmenter


def test_segmenter_finds_eight_invoices(tmp_path):
    # 8 invoices, mixed lengths: some with "Page k of N", some single-page.
    doc = fitz.open()
    lengths = [1, 3, 2, 1, 4, 1, 2, 1]
    expected = []
    page_no = 1
    for i, n in enumerate(lengths):
        expected.append((page_no, page_no + n - 1))
        for k in range(n):
            page = doc.new_page()
            if k == 0:
                lines = [ln.format(n=5000 + i) for ln in INVOICE_TEXT]
            else:
                lines = ["ACME Widgets Ltd", "continued", "Widget B  1 x 5.00  5.00"]
            if n > 1:
                lines.append(f"Page {k + 1} of {n}")
            page.insert_text((72, 72), "\n".join(lines), fontsize=11)
            page_no += 1
    path = str(tmp_path / "multi.pdf")
    doc.save(path)
    doc.close()
    assert parse_document(path, "pdf").invoice_ranges == expected


def test_segmenter_number_change_without_page_markers():
    pages = [
        ParsedPage(page_no=1, text="Invoice No: A-100\nTotal 5.00", method=PageMethod.TEXT_LAYER),
        ParsedPage(page_no=2, text="more lines for A-100 without number label", method=PageMethod.TEXT_LAYER),
        ParsedPage(page_no=3, text="Invoice No: A-101\nTotal 7.00", method=PageMethod.TEXT_LAYER),
    ]
    assert segment_pages(pages) == [(1, 2), (3, 3)]


def test_segmenter_ranges_cover_all_pages():
    pages = [ParsedPage(page_no=i, text=f"Invoice # X-{i // 3}\nTotal 1.00", method=PageMethod.TEXT_LAYER) for i in range(1, 31)]
    ranges = segment_pages(pages)
    covered = [p for a, b in ranges for p in range(a, b + 1)]
    assert covered == list(range(1, 31))


def test_segmenter_1000_pages_is_fast():
    pages = [ParsedPage(page_no=i, text=f"Invoice No: INV-{i // 3:05d}\n" + "line\n" * 40, method=PageMethod.TEXT_LAYER) for i in range(1, 1001)]
    start = time.perf_counter()
    ranges = segment_pages(pages)
    assert time.perf_counter() - start < 3
    assert len(ranges) == 334
