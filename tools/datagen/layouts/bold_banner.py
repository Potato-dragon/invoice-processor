"""Layout: Bold Banner (Dev Layout 4)
High-contrast header banner across the top, prominent invoice number and colored accent styling.
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


def render_bold_banner(invoice: InvoiceData, output_path: str) -> None:
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

    # 1. Full-width bold banner
    banner_left = Paragraph(
        "<font size='18' color='white'><b>INVOICE STATEMENT</b></font>",
        styles["Normal"],
    )

    banner_meta_style = styles["Normal"].clone("BannerMeta")
    banner_meta_style.alignment = 2
    banner_right = Paragraph(
        f"<font color='white'><b>Invoice #:</b> {invoice.invoice_number}<br/>"
        f"<b>Billing Date:</b> {invoice.display_date}</font>",
        banner_meta_style,
    )

    banner_table = Table([[banner_left, banner_right]], colWidths=[300, 240])
    banner_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#064e3b")),  # Dark emerald/forest green
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ])
    )
    story.append(banner_table)
    story.append(Spacer(1, 15))

    # 2. Addresses: Supplier on left, Customer on right
    supp_lines = ["<b>From:</b>"]
    if invoice.supplier_name:
        supp_lines.append(f"<b><font size='11'>{invoice.supplier_name}</font></b>")
    if invoice.supplier_address:
        supp_lines.append(invoice.supplier_address)
    if invoice.supplier_email or invoice.supplier_phone:
        supp_lines.append(f"{invoice.supplier_email} • {invoice.supplier_phone}")
    if invoice.supplier_tax_id:
        supp_lines.append(f"Tax Ref: {invoice.supplier_tax_id}")

    cust_lines = ["<b>Sold To:</b>"]
    if invoice.customer_name:
        cust_lines.append(f"<b><font size='11'>{invoice.customer_name}</font></b>")
        if invoice.customer_address:
            cust_lines.append(invoice.customer_address)
        if invoice.customer_tax_id:
            cust_lines.append(f"Customer Tax ID: {invoice.customer_tax_id}")
    else:
        cust_lines.append("<i>Standard Customer Sale</i>")

    addr_table = Table([
        [
            Paragraph("<br/>".join(supp_lines), styles["Normal"]),
            Paragraph("<br/>".join(cust_lines), styles["Normal"]),
        ]
    ], colWidths=[270, 270])
    addr_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(addr_table)
    story.append(Spacer(1, 15))

    # 3. Table of items
    right_style = styles["Normal"].clone("BannerRight")
    right_style.alignment = 2

    center_style = styles["Normal"].clone("BannerCenter")
    center_style.alignment = 1

    table_data = [[
        Paragraph("<b><font color='white'>Services / Products</font></b>", styles["Normal"]),
        Paragraph("<b><font color='white'>Units</font></b>", center_style),
        Paragraph("<b><font color='white'>Unit Price</font></b>", right_style),
        Paragraph("<b><font color='white'>Amount</font></b>", right_style),
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
        colWidths=[290, 50, 100, 100],
        repeatRows=1,
    )
    items_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#064e3b")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ])
    )
    story.append(items_table)
    story.append(Spacer(1, 10))

    # 4. Bottom totals
    summary_rows = []
    if invoice.subtotal is not None:
        sub_str = format_currency_amount(
            invoice.subtotal,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        summary_rows.append([
            Paragraph("<b>Subtotal:</b>", right_style),
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
            Paragraph("<b>Estimated Tax:</b>", right_style),
            Paragraph(tax_str, right_style),
        ])

    total_str = format_currency_amount(
        invoice.total,
        locale=invoice.locale,
        currency_symbol=invoice.currency_symbol,
        symbol_position=invoice.currency_position,
    )
    summary_rows.append([
        Paragraph("<b><font size='11' color='#064e3b'>Balance Due:</font></b>", right_style),
        Paragraph(f"<b><font size='11' color='#064e3b'>{total_str}</font></b>", right_style),
    ])

    summary_table = Table(summary_rows, colWidths=[400, 140])
    summary_table.setStyle(
        TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#064e3b")),
        ])
    )
    story.append(summary_table)

    doc.build(story, canvasmaker=NumberedCanvas)
