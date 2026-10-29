import pytest
from app.extraction.normalize import parse_decimal, detect_currency, parse_date


def test_parse_decimal_various_formats():
    assert parse_decimal("1,234.56") == "1234.56"
    assert parse_decimal("1.234,56") == "1234.56"
    assert parse_decimal("1 234,56") == "1234.56"
    assert parse_decimal("1 234.56") == "1234.56"
    assert parse_decimal("1,23,456.78") == "123456.78"
    assert parse_decimal("1234") == "1234.00"
    assert parse_decimal("(1,234.56)") == "-1234.56"
    assert parse_decimal("-$100") == "-100.00"
    assert parse_decimal("100-") == "-100.00"
    assert parse_decimal("€ 1.234,56") == "1234.56"
    assert parse_decimal("1234.56 USD") == "1234.56"
    assert parse_decimal(None) is None
    assert parse_decimal("") is None


def test_detect_currency():
    # Specific currencies
    assert detect_currency("Total: €100.00").currency == "EUR"
    assert detect_currency("Total: £50").currency == "GBP"
    assert detect_currency("Amount: 1,000 JPY").currency == "JPY"
    assert detect_currency("Price: ₹ 500").currency == "INR"
    assert detect_currency("Total: 1000 ৳").currency == "BDT"
    assert detect_currency("Total: USD 100").currency == "USD"
    assert detect_currency("Total: US$ 100").currency == "USD"
    assert detect_currency("Total: CAD 100").currency == "CAD"
    assert detect_currency("Total: CHF 150").currency == "CHF"

    # Bare dollar is ambiguous
    res = detect_currency("Total: $100.00")
    assert res.currency is None
    assert "CURRENCY_AMBIGUOUS" in res.notes

    res_word = detect_currency("Total: 100 Dollars")
    assert res_word.currency is None
    assert "CURRENCY_AMBIGUOUS" in res_word.notes


def test_parse_date():
    assert parse_date("2026-03-14").iso_date == "2026-03-14"
    assert parse_date("14 Mar 2026").iso_date == "2026-03-14"
    assert parse_date("March 14, 2026").iso_date == "2026-03-14"
    assert parse_date("14. März 2026").iso_date == "2026-03-14"
    assert parse_date("14 mars 2026").iso_date == "2026-03-14"
    assert parse_date("14 de marzo de 2026").iso_date == "2026-03-14"
    assert parse_date("25/12/2025").iso_date == "2025-12-25"

    # Ambiguous date
    amb = parse_date("03/04/2026")
    assert amb.iso_date is not None
    assert amb.is_ambiguous is True

