"""Layout: Minimalist Sidebar (Test Layout 1)
Modern open-table layout with left sidebar block, clean horizontal rules, and minimalist styling.
"""

from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from tools.datagen.layouts.base import NumberedCanvas, get_base_styles
from tools.datagen.models import InvoiceData
from tools.datagen.number_format import format_currency_amount


def render_minimalist_sidebar(invoice: InvoiceData, output_path: str) -> None:
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=45,
    )

    styles = get_base_styles()
    story = []

    # 1. Left sidebar block vs Right billing block
    sidebar_lines = [
        "<font size='10' color='#64748b'><b>FROM:</b></font>",
    ]
    if invoice.supplier_name:
        sidebar_lines.append(f"<b><font size='12' color='#18181b'>{invoice.supplier_name}</font></b>")
    if invoice.supplier_address:
        sidebar_lines.append(invoice.supplier_address)
    if invoice.supplier_email or invoice.supplier_phone:
        sidebar_lines.append(f"{invoice.supplier_email}<br/>{invoice.supplier_phone}")
    if invoice.supplier_tax_id:
        sidebar_lines.append(f"Tax: {invoice.supplier_tax_id}")

    sidebar_lines.extend([
        "<br/>",
        f"<b>Bill #:</b> {invoice.invoice_number}",
        f"<b>Date:</b> {invoice.display_date}",
        "<b>Payment Terms:</b> Net 30",
    ])

    right_lines = [
        "<font size='22' color='#18181b'><b>INVOICE</b></font>",
        "<br/>",
        "<font size='10' color='#64748b'><b>INVOICE TO:</b></font>",
    ]
    if invoice.customer_name:
        right_lines.append(f"<b><font size='12' color='#18181b'>{invoice.customer_name}</font></b>")
        if invoice.customer_address:
            right_lines.append(invoice.customer_address)
        if invoice.customer_tax_id:
            right_lines.append(f"Client Tax: {invoice.customer_tax_id}")
    else:
        right_lines.append("<i>Individual Customer</i>")

    top_table = Table([
        [
            Paragraph("<br/>".join(sidebar_lines), styles["Normal"]),
            Paragraph("<br/>".join(right_lines), styles["Normal"]),
        ]
    ], colWidths=[240, 300])

    top_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f4f4f5")),
            ("BOX", (0, 0), (0, 0), 0.5, colors.HexColor("#e4e4e7")),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (0, 0), 10),
            ("RIGHTPADDING", (0, 0), (0, 0), 10),
            ("LEFTPADDING", (1, 0), (1, 0), 16),
        ])
    )
    story.append(top_table)
    story.append(Spacer(1, 20))

    # 2. Minimalist open table for line items
    right_style = styles["Normal"].clone("MinRight")
    right_style.alignment = 2

    center_style = styles["Normal"].clone("MinCenter")
    center_style.alignment = 1

    table_data = [[
        Paragraph("<b>Description</b>", styles["Normal"]),
        Paragraph("<b>Qty</b>", center_style),
        Paragraph("<b>Price</b>", right_style),
        Paragraph("<b>Total</b>", right_style),
    ]]

    for item in invoice.line_items:
        formatted_price = format_currency_amount(
            item.unit_price,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        formatted_amount = format_currency_amount(
            item.amount,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        qty_str = (
            f"{item.quantity:.0f}"
            if item.quantity == item.quantity.to_integral_value()
            else str(item.quantity)
        )

        table_data.append([
            Paragraph(item.description, styles["Normal"]),
            Paragraph(qty_str, center_style),
            Paragraph(formatted_price, right_style),
            Paragraph(formatted_amount, right_style),
        ])

    items_table = Table(
        table_data,
        colWidths=[310, 50, 90, 90],
        repeatRows=1,
    )
    items_table.setStyle(
        TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#18181b")),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#18181b")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#f4f4f5")),
        ])
    )
    story.append(items_table)
    story.append(Spacer(1, 10))

    # 3. Clean right-aligned summary
    summary_rows = []
    if invoice.subtotal is not None:
        sub_str = format_currency_amount(
            invoice.subtotal,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        summary_rows.append([
            Paragraph("Subtotal", right_style),
            Paragraph(sub_str, right_style),
        ])

    if invoice.tax is not None:
        tax_str = format_currency_amount(
            invoice.tax,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        summary_rows.append([
            Paragraph("Tax", right_style),
            Paragraph(tax_str, right_style),
        ])

    total_str = format_currency_amount(
        invoice.total,
        locale=invoice.locale,
        currency_symbol=invoice.currency_symbol,
        symbol_position=invoice.currency_position,
    )
    summary_rows.append([
        Paragraph("<b>Total Amount</b>", right_style),
        Paragraph(f"<b>{total_str}</b>", right_style),
    ])

    summary_table = Table(summary_rows, colWidths=[410, 130])
    summary_table.setStyle(
        TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#18181b")),
        ])
    )
    story.append(summary_table)

    doc.build(story, canvasmaker=NumberedCanvas)
