"""Vision fallback, cache safety, and patterns from real-world invoices (31 Oct fixes)."""
import os
from unittest.mock import patch

from app.contracts import ExtractionMethod, PageMethod, ParsedPage
from app.extraction import extract_invoice
from app.extraction.limiter import LLMCache
from app.extraction.llm import FakeLLMClient
from app.extraction.rules import _has_company_suffix, _inv_token, extract_by_rules
from app.extraction.vision import normalize_value

GOOD_TEXT = "Invoice Number: INV-77\nInvoice Date: 2026-01-15\nACME Widgets Ltd\nSubtotal: 100.00\nTax: 10.00\nTotal: USD 110.00"
VISION_ANSWER = {
    "invoice_number": {"value": "9900000012345", "evidence": "Invoice No 9900000012345", "page": 1},
    "invoice_date": {"value": "06-Nov-2025", "evidence": "Invoice Date: 06-Nov-2025", "page": 1},
    "supplier_name": {"value": "Cloudco Limited", "evidence": "CLOUDCO LIMITED", "page": 1},
    "customer_name": {"value": "Example Cafe", "evidence": "Example Cafe", "page": 1},
    "subtotal": {"value": "3,293.33", "evidence": None, "page": 1},
    "tax": {"value": "164.67", "evidence": None, "page": 1},
    "total": {"value": "3,458.00", "evidence": None, "page": 1},
    "currency": {"value": "TK", "evidence": "(TK)", "page": 1},
    "line_items": [{"description": "Cloud VM", "quantity": "1", "unit_price": "1,960.00", "amount": "1,960.00"}],
}


class VisionClient:
    def __init__(self):
        self.calls = []

    def complete(self, model, prompt, images=None):
        self.calls.append((model, bool(images)))
        return dict(VISION_ANSWER) if images else {}


def _ocr_page(text: str, conf: float) -> list[ParsedPage]:
    return [ParsedPage(page_no=1, text=text, method=PageMethod.OCR, ocr_confidence=conf)]


def test_vision_used_for_garbled_scan_and_values_flagged_unverified():
    client = VisionClient()
    pages = _ocr_page("cloudco\nExmple Rd- £4, Cafe Road\nTotal ... garbled", 0.47)
    with patch.dict(os.environ, {"LLM_FAKE": "false", "GEMINI_API_KEY": "k"}):
        res = extract_invoice(pages, llm_client=client, cache=LLMCache(), page_images=lambda: [(1, b"png")])
    assert res.method == ExtractionMethod.LLM_VISION
    assert all(sent_image for _, sent_image in client.calls)
    assert res.invoice_number.value == "9900000012345"
    assert res.invoice_date.value == "2025-11-06"
    assert res.total.value == "3458.00" and res.subtotal.value == "3293.33"
    # Not visible in the OCR text -> low confidence + note, so validation asks a person.
    assert res.invoice_number.confidence < 0.6
    assert "VISION_UNVERIFIED:invoice_number" in res.notes
    assert res.line_items and res.line_items[0].amount == "1960.00"


def test_vision_not_used_for_digital_text_layer():
    client = VisionClient()
    pages = [ParsedPage(page_no=1, text="random words only", method=PageMethod.TEXT_LAYER)]
    with patch.dict(os.environ, {"LLM_FAKE": "false", "GEMINI_API_KEY": "k"}):
        extract_invoice(pages, llm_client=client, cache=LLMCache(), page_images=lambda: [(1, b"png")])
    assert not any(img for _, img in client.calls)


def test_confident_rules_values_survive_vision_on_readable_scan():
    client = VisionClient()
    pages = _ocr_page(GOOD_TEXT, 0.70)  # readable but below 0.8 -> vision runs
    with patch.dict(os.environ, {"LLM_FAKE": "false", "GEMINI_API_KEY": "k"}):
        res = extract_invoice(pages, llm_client=client, cache=LLMCache(), page_images=lambda: [(1, b"png")])
    assert res.invoice_number.value == "INV-77"  # rules value (0.7 after OCR cap) kept
    assert res.total.value == "110.00"


def test_fake_answers_are_never_cached():
    cache = LLMCache()
    pages = [ParsedPage(page_no=1, text="nothing useful here", method=PageMethod.TEXT_LAYER)]
    extract_invoice(pages, llm_client=FakeLLMClient(), cache=cache)
    assert cache._mem == {}


def test_low_ocr_confidence_caps_field_confidence():
    pages = _ocr_page(GOOD_TEXT, 0.5)
    with patch.dict(os.environ, {"LLM_FAKE": "true"}):
        res = extract_invoice(pages, llm_client=FakeLLMClient(), cache=LLMCache())
    assert res.total.value == "110.00" and res.total.confidence <= 0.5


def test_normalize_llm_values():
    assert normalize_value("total", "US$ 5,550.00") == ("5550.00", [])
    assert normalize_value("invoice_date", "22/02/2026")[0] == "2026-02-22"
    assert normalize_value("currency", "eur") == ("EUR", [])
    assert normalize_value("currency", "$") == (None, ["CURRENCY_AMBIGUOUS"])
    assert normalize_value("customer_name", "  null ") == (None, [])


def test_ocr_noise_is_not_an_invoice_number():
    assert _inv_token("1SNowaas 202:") is None
    assert _inv_token("invoice_number_1") == "invoice_number_1"
    assert _inv_token("# BLR_WFLD20151000982590") == "BLR_WFLD20151000982590"


def test_company_suffix_is_case_aware():
    assert _has_company_suffix("Shopify International Limited")
    assert _has_company_suffix("WS Retail Services Pvt. Ltd.,")
    assert _has_company_suffix("NovaStar Robotics SpA")
    assert not _has_company_suffix("* As recipient you are liable to account for reverse charge VAT as")


def _rows(*lines: str) -> list[ParsedPage]:
    return [ParsedPage(page_no=1, text="\n".join(lines), method=PageMethod.TEXT_LAYER)]


def test_real_world_labels():
    r = extract_by_rules(_rows(
        "TOTAL DUE", "€116.82 EUR", "Account billed", "EXAMPLESHOP.FI", "Bill created Feb 17", "Bill #900000001",
        "Paid on Feb 19, 2026", "30-day billing cycle", "Feb 17, 2026", "Subtotal", "€116.82 EUR", "VAT 0.0%*", "€0.00 EUR",
        "Total", "€116.82 EUR", "Shopify International Limited", "2nd Floor, 1-2 Victoria Buildings", "VAT IE3347697KH",
    ))
    assert r.invoice_number.value == "900000001"
    assert r.invoice_date.value == "2026-02-17"  # not the "Paid on" date
    assert r.customer_name.value == "EXAMPLESHOP.FI"
    assert r.supplier_name.value == "Shopify International Limited"
    assert (r.subtotal.value, r.tax.value, r.total.value, r.currency.value) == ("116.82", "0.00", "116.82", "EUR")


def test_dutch_invoice_and_value_before_label():
    r = extract_by_rules(_rows(
        "FACTUUR.\tCoolblue B.V.", "Pino Bluebird", "Factuurnummer: 993548900", "Factuurdatum: 19 april 2014",
        "Exclusief BTW\t€ 593,36\tSubtotaal\t€ 717,97", "BTW 21%\t€ 124,61", "Totaal\t€ 717,97",
    ))
    assert r.invoice_number.value == "993548900"
    assert r.invoice_date.value == "2014-04-19"
    assert (r.subtotal.value, r.tax.value, r.total.value) == ("593.36", "124.61", "717.97")
    r = extract_by_rules(_rows("WS Retail Services Pvt. Ltd.,", "Sold By :", "VAT/TIN: 29670869006", "Grand Total 319.00 Rs"))
    assert r.supplier_name.value == "WS Retail Services Pvt. Ltd."
    assert r.tax.value is None  # a VAT/TIN number is not a tax amount


def test_aws_style_attn_and_service_provider():
    r = extract_by_rules(_rows(
        "Service Provider:", "(Not to be used for payment remittance)", "Amazon Web Services, Inc.",
        "Bill to Address:", "ATTN: iViveLabs Limited", "Invoice Number:", "42183017", "Invoice Date:", "August 3 , 2014",
        "All charges and prices are in US Dollars", "TOTAL AMOUNT DUE ON August 3 , 2014", "$4.11",
    ))
    assert r.supplier_name.value == "Amazon Web Services, Inc."
    assert r.customer_name.value == "iViveLabs Limited"
    assert r.invoice_date.value == "2014-08-03"
    assert r.currency.value == "USD"


def test_column_header_does_not_win_over_real_subtotal():
    # "Montant HT / Total" is a column header: the amount under it is the first
    # row, not the subtotal. The real subtotal is the one that adds up with tax.
    r = extract_by_rules(_rows(
        "NovaStar Robotics SpA\tFACTURE / INVOICE", "Facture N° / Invoice No: INV-2026-U080",
        "Designation / Description\tQte / Qty\tPrix Unit. / Rate\tMontant HT / Total",
        "Machine Learning Model Tuning Service\t2\t3.200,00 €\t6.400,00 €",
        "Backup Battery UPS Module 1500VA\t3\t380,00 €\t1.140,00 €",
        "Total Hors Taxes (HT):\t7.540,00 €", "TVA / Tax (22%):\t1.658,80 €", "Total Toutes Taxes Comprises (TTC):\t9.198,80 €",
    ))
    assert (r.subtotal.value, r.tax.value, r.total.value) == ("7540.00", "1658.80", "9198.80")


def test_line_items_with_detail_rows_underneath():
    # Each item has one-cell detail rows under it ("Description: ...", "Tax: 0.2%");
    # they must not end the table.
    r = extract_by_rules(_rows(
        "Item\tQuantity\tRate\tAmount",
        "Service A\t12\t$10.00\t$120.00", "Description: Repair", "Parts: 1 x cap_a", "Tax: 0.2%",
        "Service B\t5\t$1.50\t$7.50", "Description: Cleaning", "Tax: 0.4%",
        "Subtotal:\t$127.50", "Tax (0%):\t$0.00", "Total:\t$127.50",
    ))
    assert [(li.description, li.amount) for li in r.line_items] == [("Service A", "120.00"), ("Service B", "7.50")]
    assert (r.subtotal.value, r.tax.value, r.total.value) == ("127.50", "0.00", "127.50")
