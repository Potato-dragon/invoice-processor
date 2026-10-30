"""Number and currency formatting utilities supporting multiple locales."""

from decimal import Decimal
from typing import Optional


def format_currency_amount(
    amount: Decimal,
    locale: str = "en_US",
    currency_symbol: str = "$",
    symbol_position: str = "prefix",
    ambiguous: bool = False,
    decimals: int = 2,
) -> str:
    """Format a Decimal amount according to locale rules."""
    # Handle decimal digits
    if decimals == 0:
        val_str = f"{amount:.0f}"
        int_part = val_str
        dec_part = ""
    else:
        val_str = f"{amount:.{decimals}f}"
        parts = val_str.split(".")
        int_part = parts[0]
        dec_part = parts[1]

    # Format integer part with thousands separators
    if locale in ("de_DE", "es_ES", "it_IT"):
        # Period thousands separator, comma decimal separator (1.234,56)
        formatted_int = _add_thousands_sep(int_part, sep=".")
        formatted_num = f"{formatted_int},{dec_part}" if dec_part else formatted_int
    elif locale in ("fr_FR", "sv_SE", "nb_NO"):
        # Space thousands separator, comma decimal separator (1 234,56)
        formatted_int = _add_thousands_sep(int_part, sep=" ")
        formatted_num = f"{formatted_int},{dec_part}" if dec_part else formatted_int
    elif locale in ("hi_IN", "bn_BD"):
        # South Asian grouping (1,23,456.78)
        formatted_int = _format_indian_numbering(int_part)
        formatted_num = f"{formatted_int}.{dec_part}" if dec_part else formatted_int
    else:
        # Standard US/UK/International (1,234.56)
        formatted_int = _add_thousands_sep(int_part, sep=",")
        formatted_num = f"{formatted_int}.{dec_part}" if dec_part else formatted_int

    if not currency_symbol:
        return formatted_num

    if symbol_position == "prefix":
        # e.g. "$1,234.56" or "€ 1.234,56"
        sep = " " if len(currency_symbol) > 1 or currency_symbol in ("€", "৳", "₹", "¥") else ""
        return f"{currency_symbol}{sep}{formatted_num}"
    else:
        # e.g. "1.234,56 €"
        return f"{formatted_num} {currency_symbol}"


def _add_thousands_sep(int_str: str, sep: str = ",") -> str:
    """Add grouping separator every 3 digits from right."""
    is_neg = int_str.startswith("-")
    if is_neg:
        int_str = int_str[1:]

    parts = []
    while len(int_str) > 3:
        parts.insert(0, int_str[-3:])
        int_str = int_str[:-3]
    if int_str:
        parts.insert(0, int_str)

    res = sep.join(parts)
    return f"-{res}" if is_neg else res


def _format_indian_numbering(int_str: str) -> str:
    """Format integer part according to Indian numbering system (e.g. 12,34,567)."""
    is_neg = int_str.startswith("-")
    if is_neg:
        int_str = int_str[1:]

    if len(int_str) <= 3:
        res = int_str
    else:
        last_three = int_str[-3:]
        remaining = int_str[:-3]
        parts = []
        while len(remaining) > 2:
            parts.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            parts.insert(0, remaining)
        res = f"{','.join(parts)},{last_three}"

    return f"-{res}" if is_neg else res


def display_symbol(symbol: str, ambiguous: bool) -> str:
    """Symbol as printed on the PDF.

    - A plain "$" is printed only for deliberately ambiguous documents
      (DECISIONS 11: bare $ -> currency null + CURRENCY_AMBIGUOUS). Normal USD
      documents print "US$" so the currency is actually on the page.
    - Helvetica has no rupee or taka glyph (they rendered as "I" in the text
      layer), so INR/BDT print their ISO code, as many real invoices do.
    """
    if symbol == "$" and not ambiguous:
        return "US$"
    return {"₹": "INR", "৳": "BDT"}.get(symbol, symbol)
