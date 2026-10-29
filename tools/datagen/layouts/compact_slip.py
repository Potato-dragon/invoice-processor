"""Layout: Compact Slip (Dev Layout 3)
Dense, compact layout suitable for service vouchers and tax invoice slips.
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


def render_compact_slip(invoice: InvoiceData, output_path: str) -> None:
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=30,
        bottomMargin=40,
    )

    styles = get_base_styles()
    story = []

    # 1. Header bar
    title_style = styles["Normal"].clone("SlipTitle")
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 14
    title_style.textColor = colors.HexColor("#1e1b4b")

    meta_style = styles["Normal"].clone("SlipMeta")
    meta_style.alignment = 2

    header_data = [[
        Paragraph("TAX INVOICE", title_style),
        Paragraph(
            f"<b>Doc Ref #:</b> {invoice.invoice_number}<br/><b>Tax Date:</b> {invoice.display_date}",
            meta_style,
        ),
    ]]
    header_table = Table(header_data, colWidths=[270, 270])
    header_table.setStyle(
        TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor("#1e1b4b")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(header_table)
    story.append(Spacer(1, 10))

    # 2. Side-by-side From / Client details
    from_lines = ["<b>From:</b>"]
    if invoice.supplier_name:
        from_lines.append(f"<b>{invoice.supplier_name}</b>")
    if invoice.supplier_address:
        from_lines.append(invoice.supplier_address)
    if invoice.supplier_tax_id:
        from_lines.append(f"Tax Reg: {invoice.supplier_tax_id}")

    to_lines = ["<b>Client:</b>"]
    if invoice.customer_name:
        to_lines.append(f"<b>{invoice.customer_name}</b>")
        if invoice.customer_address:
            to_lines.append(invoice.customer_address)
        if invoice.customer_tax_id:
            to_lines.append(f"Tax Ref: {invoice.customer_tax_id}")
    else:
        to_lines.append("<i>Walk-in / Direct Client</i>")

    addr_data = [[
        Paragraph("<br/>".join(from_lines), styles["Small"]),
        Paragraph("<br/>".join(to_lines), styles["Small"]),
    ]]
    addr_table = Table(addr_data, colWidths=[270, 270])
    addr_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])
    )
    story.append(addr_table)
    story.append(Spacer(1, 10))

    # 3. Dense Table for items
    table_data = [[
        Paragraph("<b><font color='white'>Item Description</font></b>", styles["Small"]),
        Paragraph("<b><font color='white'>Qty</font></b>", styles["Small"]),
        Paragraph("<b><font color='white'>Unit Cost</font></b>", styles["Small"]),
        Paragraph("<b><font color='white'>Total Amount</font></b>", styles["Small"]),
    ]]

    right_style = styles["Small"].clone("SlipRight")
    right_style.alignment = 2

    center_style = styles["Small"].clone("SlipCenter")
    center_style.alignment = 1

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
            Paragraph(item.description, styles["Small"]),
            Paragraph(qty_str, center_style),
            Paragraph(formatted_price, right_style),
            Paragraph(formatted_amount, right_style),
        ])

    dense_table = Table(
        table_data,
        colWidths=[290, 50, 100, 100],
        repeatRows=1,
    )
    dense_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e1b4b")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ])
    )
    story.append(dense_table)
    story.append(Spacer(1, 8))

    # 4. Summary
    summary_rows = []
    if invoice.subtotal is not None:
        sub_str = format_currency_amount(
            invoice.subtotal,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        summary_rows.append([
            Paragraph("<b>Sub-Total:</b>", right_style),
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
            Paragraph("<b>GST / Tax:</b>", right_style),
            Paragraph(tax_str, right_style),
        ])

    total_str = format_currency_amount(
        invoice.total,
        locale=invoice.locale,
        currency_symbol=invoice.currency_symbol,
        symbol_position=invoice.currency_position,
    )
    summary_rows.append([
        Paragraph("<b>Grand Total:</b>", right_style),
        Paragraph(f"<b>{total_str}</b>", right_style),
    ])

    summary_table = Table(summary_rows, colWidths=[400, 140])
    summary_table.setStyle(
        TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1e1b4b")),
        ])
    )
    story.append(summary_table)

    doc.build(story, canvasmaker=NumberedCanvas)
