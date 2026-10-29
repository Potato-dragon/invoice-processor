"""Locale-safe normalization utilities for amounts, dates, and currencies."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

# ISO 4217 Currency mapping and patterns
CURRENCY_SYMBOLS: dict[str, str] = {
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "৳": "BDT",
    "CHF": "BDT", # will override below
}
CURRENCY_SYMBOLS["CHF"] = "CHF"

CURRENCY_WORDS: dict[str, str] = {
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "jpy": "JPY",
    "yen": "JPY",
    "inr": "INR",
    "rupee": "INR",
    "rupees": "INR",
    "bdt": "BDT",
    "taka": "BDT",
    "tk": "BDT",
    "chf": "CHF",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "cad": "CAD",
    "canadian dollar": "CAD",
    "aud": "AUD",
    "australian dollar": "AUD",
}

# Regex for currency detection
ISO_CURRENCY_PATTERN = re.compile(r"\b([A-Z]{3})\b")

MONTH_NAMES: dict[str, int] = {
    # English
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
    # German
    "januar": 1, "jän": 1, "jäner": 1,
    "februar": 2,
    "märz": 3, "maerz": 3, "mrz": 3,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "oktober": 10, "okt": 10,
    "dezember": 12, "dez": 12,
    # French
    "janvier": 1, "janv": 1,
    "février": 2, "fevrier": 2, "févr": 2, "fevr": 2,
    "mars": 3,
    "avril": 4, "avr": 4,
    "juin": 6,
    "juillet": 7, "juil": 7,
    "août": 8, "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12, "decembre": 12,
    # Spanish
    "enero": 1, "ene": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4, "abr": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12, "dic": 12,
}


class CurrencyResult(NamedTuple):
    currency: str | None
    notes: list[str]


class DateResult(NamedTuple):
    iso_date: str | None
    is_ambiguous: bool


def parse_decimal(raw: str | None) -> str | None:
    """Parse a number string in various locales to a standard decimal string (e.g. '1234.56').

    Handles:
    - 1,234.56 (US/UK)
    - 1.234,56 (German/Spanish)
    - 1 234,56 or 1 234.56 (French/space grouping)
    - 1,23,456.78 (Indian lakh/crore)
    - Parentheses: (1,234.56) -> -1234.56
    - Leading/trailing minus: -$100 or 100- -> -100.00
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None

    # Check for negative in parentheses e.g. (123.45) or with minus sign
    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
    elif s.startswith("-"):
        is_negative = True
        s = s[1:].strip()
    elif s.endswith("-"):
        is_negative = True
        s = s[:-1].strip()

    # Strip currency symbols and whitespace
    # Keep digits, dots, commas, spaces, and apostrophes
    cleaned = ""
    for ch in s:
        if ch.isdigit() or ch in "., '":
            cleaned += ch
    cleaned = cleaned.strip()
    if not cleaned:
        return None

    # Remove trailing/leading apostrophes or spaces
    cleaned = cleaned.replace("'", "")

    # Analyze dot and comma separators
    has_dot = "." in cleaned
    has_comma = "," in cleaned
    has_space = " " in cleaned

    normalized: str

    if has_space:
        # e.g., '1 234,56' or '1 234.56' or '1 234'
        if has_comma and not has_dot:
            # German/French with comma decimal: 1 234,56
            parts = cleaned.rsplit(",", 1)
            int_part = parts[0].replace(" ", "").replace(".", "")
            dec_part = parts[1]
            normalized = f"{int_part}.{dec_part}"
        elif has_dot and not has_comma:
            # 1 234.56
            parts = cleaned.rsplit(".", 1)
            int_part = parts[0].replace(" ", "")
            dec_part = parts[1]
            normalized = f"{int_part}.{dec_part}"
        else:
            # 1 234 or mixed
            normalized = cleaned.replace(" ", "")

    elif has_dot and has_comma:
        # Both dot and comma present
        last_dot = cleaned.rfind(".")
        last_comma = cleaned.rfind(",")
        if last_comma > last_dot:
            # European format: 1.234,56 or 1.234.567,89
            int_part = cleaned[:last_comma].replace(".", "")
            dec_part = cleaned[last_comma + 1:]
            normalized = f"{int_part}.{dec_part}"
        else:
            # US/UK or Indian format: 1,234.56 or 1,23,456.78
            int_part = cleaned[:last_dot].replace(",", "")
            dec_part = cleaned[last_dot + 1:]
            normalized = f"{int_part}.{dec_part}"

    elif has_comma:
        # Only comma: could be 1,234 (thousands) or 1234,56 (decimal) or 1,234,567
        comma_count = cleaned.count(",")
        parts = cleaned.split(",")
        if comma_count == 1:
            if len(parts[1]) == 2:
                # Almost certainly decimal: 1234,56
                normalized = f"{parts[0]}.{parts[1]}"
            elif len(parts[1]) == 3 and len(parts[0]) <= 3:
                # Could be 1,000 (thousands)
                normalized = cleaned.replace(",", "")
            else:
                # e.g. 12,5 -> decimal
                normalized = f"{parts[0]}.{parts[1]}"
        else:
            # Multiple commas: 1,234,567 -> thousands separators
            normalized = cleaned.replace(",", "")

    elif has_dot:
        # Only dot: could be 1,234.56 without thousands, or European 1.234
        dot_count = cleaned.count(".")
        parts = cleaned.split(".")
        if dot_count == 1:
            if len(parts[1]) == 3 and len(parts[0]) <= 3 and not (len(parts[0]) == 0):
                # Ambiguous: could be European thousands 1.000 or US 1.000 (3 decimal places)
                # In invoice contexts, if exactly 2 decimal places it is decimal; if 3 decimal places without prior commas,
                # e.g. quantity 1.500 or amount 1.000. For amounts, standard decimals are typically 2 digits.
                # However, if it's 1.25 -> decimal. If 1.000 -> standard decimal representation 1.000 or 1000?
                # Usually 1.234 in US is 1.234, in DE is 1234. If unsure, treat dot as decimal separator
                normalized = cleaned
            else:
                normalized = cleaned
        else:
            # Multiple dots: 1.234.567 -> European thousands
            normalized = cleaned.replace(".", "")
    else:
        normalized = cleaned

    try:
        dec = Decimal(normalized)
        if is_negative:
            dec = -abs(dec)
        # Format as string with at least 2 decimal places if it had decimals, or format standard
        # The contract asks for decimal string, e.g. "1234.56"
        return f"{dec:.2f}"
    except InvalidOperation:
        return None


def detect_currency(text: str | None) -> CurrencyResult:
    """Detect currency from text.

    If a bare '$' is found without USD/CAD/AUD context, returns (None, ['CURRENCY_AMBIGUOUS']).
    """
    if not text:
        return CurrencyResult(None, [])

    # Check for explicit ISO codes first: USD, EUR, GBP, JPY, INR, BDT, CAD, AUD, CHF
    # Look for USD / US Dollar / US$
    if re.search(r"\bUSD\b", text, re.IGNORECASE) or re.search(r"\bUS\s*\$", text, re.IGNORECASE):
        return CurrencyResult("USD", [])
    if re.search(r"\bCAD\b", text, re.IGNORECASE) or re.search(r"\bC\s*\$", text, re.IGNORECASE):
        return CurrencyResult("CAD", [])
    if re.search(r"\bAUD\b", text, re.IGNORECASE) or re.search(r"\bA\s*\$", text, re.IGNORECASE):
        return CurrencyResult("AUD", [])

    # Check symbols
    if "€" in text:
        return CurrencyResult("EUR", [])
    if "£" in text:
        return CurrencyResult("GBP", [])
    if "¥" in text:
        return CurrencyResult("JPY", [])
    if "₹" in text:
        return CurrencyResult("INR", [])
    if "৳" in text:
        return CurrencyResult("BDT", [])

    # Check currency words/codes
    lower = text.lower()
    for word, iso in CURRENCY_WORDS.items():
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, lower):
            if iso == "USD" and word in ("dollar", "dollars"):
                # Bare "dollar" without US/Canadian/Australian qualifier is ambiguous
                return CurrencyResult(None, ["CURRENCY_AMBIGUOUS"])
            return CurrencyResult(iso, [])

    # Check other ISO 4217 3-letter uppercase codes
    for m in ISO_CURRENCY_PATTERN.finditer(text):
        code = m.group(1)
        if code in ("EUR", "GBP", "JPY", "INR", "BDT", "CHF", "USD", "CAD", "AUD", "NZD", "SGD", "SEK", "NOK", "DKK", "PLN", "ZAR", "BRL", "MXN", "CNY", "HKD"):
            return CurrencyResult(code, [])

    # Bare '$' symbol
    if "$" in text:
        return CurrencyResult(None, ["CURRENCY_AMBIGUOUS"])

    return CurrencyResult(None, [])


def parse_date(raw: str | None, doc_text: str | None = None) -> DateResult:
    """Parse date to ISO 8601 (YYYY-MM-DD).

    Returns (iso_date, is_ambiguous).
    """
    if not raw:
        return DateResult(None, False)

    s = raw.strip()
    # Normalize extra spaces and punctuation
    s = re.sub(r"[,/.-]+", " ", s).strip()

    # Try ISO YYYY-MM-DD first from raw
    iso_match = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", raw)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        try:
            dt = datetime(y, m, d)
            return DateResult(dt.strftime("%Y-%m-%d"), False)
        except ValueError:
            pass

    # Check for text month: "14 Mar 2026", "March 14, 2026", "14. März 2026"
    tokens = [t.lower() for t in s.split()]
    found_month: int | None = None
    month_token_idx: int | None = None
    for idx, tok in enumerate(tokens):
        cleaned_tok = tok.rstrip(".")
        if cleaned_tok in MONTH_NAMES:
            found_month = MONTH_NAMES[cleaned_tok]
            month_token_idx = idx
            break

    if found_month is not None and month_token_idx is not None:
        remaining_digits = [int(tok) for idx, tok in enumerate(tokens) if idx != month_token_idx and tok.isdigit()]
        if len(remaining_digits) >= 2:
            # Usually one is day (1-31) and one is year (e.g. 2024 or 24)
            year: int | None = None
            day: int | None = None
            for num in remaining_digits:
                if num > 31:
                    year = num if num >= 100 else 2000 + num
                else:
                    if day is None:
                        day = num
                    elif year is None:
                        year = 2000 + num if num < 100 else num

            if day is not None and year is not None:
                try:
                    dt = datetime(year, found_month, day)
                    return DateResult(dt.strftime("%Y-%m-%d"), False)
                except ValueError:
                    pass

    # Pure numeric dates: DD/MM/YYYY or MM/DD/YYYY or YYYY/MM/DD
    num_match = re.search(r"\b(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})\b", raw)
    if num_match:
        p1, p2, p3 = int(num_match.group(1)), int(num_match.group(2)), int(num_match.group(3))
        # Case 1: YYYY-MM-DD
        if p1 > 31:
            year, m, d = p1, p2, p3
            try:
                dt = datetime(year, m, d)
                return DateResult(dt.strftime("%Y-%m-%d"), False)
            except ValueError:
                return DateResult(None, False)

        # Case 2: p3 is year
        year = p3 if p3 >= 100 else 2000 + p3

        # Check if one is definitely > 12 (must be day)
        if p1 > 12 and p2 <= 12:
            # DD/MM/YYYY
            try:
                dt = datetime(year, p2, p1)
                return DateResult(dt.strftime("%Y-%m-%d"), False)
            except ValueError:
                return DateResult(None, False)
        elif p2 > 12 and p1 <= 12:
            # MM/DD/YYYY
            try:
                dt = datetime(year, p1, p2)
                return DateResult(dt.strftime("%Y-%m-%d"), False)
            except ValueError:
                return DateResult(None, False)
        elif p1 <= 12 and p2 <= 12:
            # Truly ambiguous! E.g. 03/04/2026
            # Use document cues if available
            day_first = True
            if doc_text:
                lower_doc = doc_text.lower()
                if "mm/dd/yyyy" in lower_doc or "mm/dd/yy" in lower_doc:
                    day_first = False
                elif "dd/mm/yyyy" in lower_doc or "dd/mm/yy" in lower_doc:
                    day_first = True

            d, m = (p1, p2) if day_first else (p2, p1)
            try:
                dt = datetime(year, m, d)
                return DateResult(dt.strftime("%Y-%m-%d"), True)
            except ValueError:
                return DateResult(None, False)

    return DateResult(None, False)
