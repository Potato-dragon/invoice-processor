from io import BytesIO

import pytest

from app.contracts import (
    ErrorCode,
    ExtractedField,
    ExtractionMethod,
    ExtractionResult,
    PageMethod,
    ParsedDocument,
    ParsedPage,
)
from app.storage import LocalStorage


def test_parsed_document_matches_lane_interface() -> None:
    document = ParsedDocument(pages=[ParsedPage(page_no=1, text="Invoice", method=PageMethod.TEXT_LAYER)])
    assert document.pages[0].page_no == 1
    assert document.invoice_ranges == []


def test_non_null_extraction_requires_evidence() -> None:
    with pytest.raises(ValueError):
        ExtractedField(value="INV-1", confidence=0.9, evidence=None, page=1)


def test_extraction_result_preserves_decimal_strings() -> None:
    empty = ExtractedField(confidence=0)
    result = ExtractionResult(
        invoice_number=empty, invoice_date=empty, supplier_name=empty, customer_name=empty,
        subtotal=ExtractedField(value="10.00", confidence=1, evidence="10.00", page=1),
        tax=empty, total=empty, currency=empty, method=ExtractionMethod.RULES,
    )
    assert result.subtotal.value == "10.00"


def test_local_storage_uses_generated_key_and_round_trips(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    key = storage.save(BytesIO(b"receipt"))
    assert key != "customer-invoice.pdf"
    with storage.open(key) as stored:
        assert stored.read() == b"receipt"
    storage.delete(key)
    assert not (tmp_path / key).exists()


def test_local_storage_rejects_path_traversal(tmp_path) -> None:
    with pytest.raises(Exception) as error:
        LocalStorage(tmp_path).open("../outside")
    assert ErrorCode.STORAGE_ERROR.value in str(error.value)
