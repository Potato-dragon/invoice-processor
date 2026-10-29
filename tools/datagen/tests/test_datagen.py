"""Unit tests for synthetic data generation and verification."""

import sys
from decimal import Decimal
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.datagen.config import (
    DEV_LAYOUTS,
    TEST_LAYOUTS,
    DEV_SUPPLIERS,
    TEST_SUPPLIERS,
)
from tools.datagen.generators.digital_pdf import build_digital_pdf_dataset
from tools.datagen.models import InvoiceData, LineItem
from tools.datagen.number_format import format_currency_amount
from tools.datagen.verify import verify_dataset


def test_number_formatting():
    # US format
    us_val = format_currency_amount(
        Decimal("1234.56"),
        locale="en_US",
        currency_symbol="$",
        symbol_position="prefix",
    )
    assert us_val == "$1,234.56"

    # German format: dot thousands, comma decimal
    de_val = format_currency_amount(
        Decimal("1234.56"),
        locale="de_DE",
        currency_symbol="€",
        symbol_position="suffix",
    )
    assert de_val == "1.234,56 €"

    # French format: space thousands, comma decimal
    fr_val = format_currency_amount(
        Decimal("1234.56"),
        locale="fr_FR",
        currency_symbol="€",
        symbol_position="suffix",
    )
    assert fr_val == "1 234,56 €"

    # Indian format: 1,23,456.78
    in_val = format_currency_amount(
        Decimal("123456.78"),
        locale="hi_IN",
        currency_symbol="₹",
        symbol_position="prefix",
    )
    assert in_val == "₹ 1,23,456.78"


def test_splits_are_strictly_disjoint():
    dev_layout_set = set(DEV_LAYOUTS)
    test_layout_set = set(TEST_LAYOUTS)
    assert dev_layout_set.isdisjoint(test_layout_set), "Dev and test layouts must be disjoint!"

    dev_supplier_set = {s["name"] for s in DEV_SUPPLIERS}
    test_supplier_set = {s["name"] for s in TEST_SUPPLIERS}
    assert dev_supplier_set.isdisjoint(test_supplier_set), "Dev and test suppliers must be disjoint!"


def test_label_no_floats_and_valid_structure():
    item = LineItem(
        description="Widget Pro",
        quantity=Decimal("2"),
        unit_price=Decimal("49.99"),
        amount=Decimal("99.98"),
    )
    inv = InvoiceData(
        id="syn_test_01",
        filename="syn_test_01.pdf",
        invoice_number="INV-001",
        invoice_date="2026-03-14",
        supplier_name="Test Supplier",
        customer_name="Test Customer",
        line_items=[item],
        subtotal=Decimal("99.98"),
        tax_rate=Decimal("0.10"),
        tax=Decimal("10.00"),
        total=Decimal("109.98"),
        currency="USD",
    )

    label = inv.to_label_dict()

    assert label["invoice_number"]["value"] == "INV-001"
    assert label["invoice_date"]["value"] == "2026-03-14"
    assert label["subtotal"]["value"] == "99.98"
    assert label["tax"]["value"] == "10.00"
    assert label["total"]["value"] == "109.98"
    assert label["currency"]["value"] == "USD"
    assert label["invoice_count"] == 1

    # Check for absence of float types
    for key, field in label.items():
        if isinstance(field, dict) and "value" in field:
            assert not isinstance(field["value"], float)
        assert not isinstance(field, float)

    for li in label["line_items"]:
        assert isinstance(li["quantity"], str)
        assert isinstance(li["unit_price"], str)
        assert isinstance(li["amount"], str)
        assert not isinstance(li["unit_price"], float)


def test_generator_determinism():
    rng1 = random.Random(42)
    invoices1 = build_digital_pdf_dataset(rng1)

    rng2 = random.Random(42)
    invoices2 = build_digital_pdf_dataset(rng2)

    assert len(invoices1) == len(invoices2)
    for inv1, inv2 in zip(invoices1, invoices2):
        assert inv1.id == inv2.id
        assert inv1.invoice_number == inv2.invoice_number
        assert inv1.total == inv2.total
        assert inv1.split == inv2.split
        assert inv1.layout == inv2.layout
        assert inv1.supplier_name == inv2.supplier_name


def test_dataset_verification_passes():
    data_dir = Path(__file__).resolve().parent.parent.parent.parent / "data"
    passed = verify_dataset(data_dir)
    assert passed is True
