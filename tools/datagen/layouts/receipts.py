"""Receipt layouts (DECISIONS 10): receipts use the invoice label object.

- receipt_thermal (dev): narrow 80 mm till slip, monospaced, one string per row.
- receipt_retail (test): A6 shop/restaurant receipt with "qty @ price" rows.
The receipt number is the invoice_number, the merchant is the supplier_name,
and there is no customer.
"""
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from tools.datagen.models import InvoiceData
from tools.datagen.number_format import format_currency_amount


def _money(inv: InvoiceData, amount) -> str:  # noqa: ANN001
    return format_currency_amount(amount, locale=inv.locale, currency_symbol=inv.currency_symbol,
                                  symbol_position=inv.currency_position)


def render_receipt_thermal(inv: InvoiceData, output_path: str) -> None:
    width = 80 * mm
    rows = 26 + 2 * len(inv.line_items)
    height = max(140 * mm, rows * 11 + 40)
    c = canvas.Canvas(output_path, pagesize=(width, height), invariant=1)
    y = height - 28

    def line(text: str, size: int = 8, bold: bool = False, center: bool = False) -> None:
        nonlocal y
        c.setFont("Courier-Bold" if bold else "Courier", size)
        if center:
            c.drawCentredString(width / 2, y, text)
        else:
            c.drawString(10, y, text)
        y -= size + 4

    def pair(label: str, value: str, bold: bool = False) -> None:
        line(f"{label:<14}{value:>20}", bold=bold)

    line(inv.supplier_name or "", 10, bold=True, center=True)
    for part in inv.supplier_address.split(", ")[:3]:
        line(part, 7, center=True)
    if inv.supplier_tax_id:
        line(f"VAT Reg {inv.supplier_tax_id}", 7, center=True)
    y -= 4
    line("SALES RECEIPT", 9, bold=True, center=True)
    line(f"Receipt No: {inv.invoice_number}")
    line(f"Date: {inv.display_date}  14:32")
    line("-" * 34)
    for item in inv.line_items:
        qty = f"{item.quantity:.0f}"
        line(f"{item.description[:16]:<16} {qty:>2} x {_money(inv, item.unit_price):>8} {_money(inv, item.amount):>9}"[:60], 7)
    line("-" * 34)
    if inv.subtotal is not None:
        pair("SUBTOTAL", _money(inv, inv.subtotal))
    if inv.tax is not None:
        rate = f" {int(inv.tax_rate * 100)}%" if inv.tax_rate else ""
        pair(f"VAT{rate}", _money(inv, inv.tax))
    pair("TOTAL", _money(inv, inv.total), bold=True)
    pair("CARD", _money(inv, inv.total))
    y -= 6
    line("Thank you for your visit!", 7, center=True)
    c.showPage()
    c.save()


def render_receipt_retail(inv: InvoiceData, output_path: str) -> None:
    width, height = 105 * mm, 148 * mm + 12 * max(0, len(inv.line_items) - 8)
    c = canvas.Canvas(output_path, pagesize=(width, height), invariant=1)
    y = height - 34
    c.setFont("Helvetica-Bold", 13)
    c.drawString(18, y, inv.supplier_name or "")
    y -= 14
    c.setFont("Helvetica", 7.5)
    c.drawString(18, y, inv.supplier_address)
    y -= 10
    if inv.supplier_tax_id:
        c.drawString(18, y, f"Tax No. {inv.supplier_tax_id}")
        y -= 10
    y -= 10
    c.setFont("Helvetica-Bold", 11)
    c.drawString(18, y, "Receipt")
    y -= 16
    c.setFont("Helvetica", 8.5)
    c.drawString(18, y, f"Receipt #: {inv.invoice_number}")
    y -= 12
    c.drawString(18, y, f"Date: {inv.display_date}")
    y -= 18
    for item in inv.line_items:
        qty = f"{item.quantity:.0f}"
        c.drawString(18, y, f"{item.description[:28]}  {qty} @ {_money(inv, item.unit_price)}  {_money(inv, item.amount)}")
        y -= 12
    y -= 6
    c.line(18, y + 8, width - 18, y + 8)
    for label, amount, bold in (("Subtotal", inv.subtotal, False), ("Tax", inv.tax, False), ("Total", inv.total, True)):
        if amount is None:
            continue
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9 if bold else 8.5)
        rate = f" ({int(inv.tax_rate * 100)}%)" if label == "Tax" and inv.tax_rate else ""
        c.drawString(18, y, f"{label}{rate}: {_money(inv, amount)}")
        y -= 13
    y -= 10
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(18, y, "Merci et a bientot / Thank you")
    c.showPage()
    c.save()
