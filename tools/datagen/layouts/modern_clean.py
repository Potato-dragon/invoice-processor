"""Layout: Modern Clean (Dev Layout 1)
Modern corporate layout with blue accents, alternating row stripes, and clear hierarchy.
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


def render_modern_clean(invoice: InvoiceData, output_path: str) -> None:
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=40,
        bottomMargin=45,
    )

    styles = get_base_styles()
    story = []

    # 1. Header: Supplier info on left, Invoice title & metadata on right
    supplier_lines = []
    if invoice.supplier_name:
        supplier_lines.append(f"<b><font size='14' color='#0f172a'>{invoice.supplier_name}</font></b>")
    if invoice.supplier_address:
        supplier_lines.append(invoice.supplier_address)
    if invoice.supplier_email or invoice.supplier_phone:
        supplier_lines.append(f"{invoice.supplier_email} • {invoice.supplier_phone}")
    if invoice.supplier_tax_id:
        supplier_lines.append(f"Tax ID: {invoice.supplier_tax_id}")

    left_header = Paragraph("<br/>".join(supplier_lines), styles["Normal"])

    meta_lines = [
        "<font size='22' color='#0284c7'><b>INVOICE</b></font>",
        f"<b>Invoice Number:</b> {invoice.invoice_number}",
        f"<b>Invoice Date:</b> {invoice.display_date}",
    ]
    if invoice.due_date:
        meta_lines.append(f"<b>Due Date:</b> {invoice.due_date}")

    meta_style = styles["Normal"].clone("RightMeta")
    meta_style.alignment = 2  # Right align
    right_header = Paragraph("<br/>".join(meta_lines), meta_style)

    header_table = Table([[left_header, right_header]], colWidths=[310, 230])
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(header_table)
    story.append(Spacer(1, 15))

    # 2. Customer billing block
    if invoice.customer_name:
        cust_lines = [
            "<font size='10' color='#0284c7'><b>BILL TO:</b></font>",
            f"<b>{invoice.customer_name}</b>",
        ]
        if invoice.customer_address:
            cust_lines.append(invoice.customer_address)
        if invoice.customer_tax_id:
            cust_lines.append(f"Tax ID: {invoice.customer_tax_id}")

        cust_p = Paragraph("<br/>".join(cust_lines), styles["Normal"])
        cust_table = Table([[cust_p]], colWidths=[540])
        cust_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ])
        )
        story.append(cust_table)
        story.append(Spacer(1, 15))

    # 3. Line Items Table
    hdr_style = styles["Normal"].clone("CleanHdr")
    hdr_style.fontName = "Helvetica-Bold"
    hdr_style.textColor = colors.white

    hdr_center = hdr_style.clone("CleanHdrCenter")
    hdr_center.alignment = 1

    hdr_right = hdr_style.clone("CleanHdrRight")
    hdr_right.alignment = 2

    table_data = [[
        Paragraph("#", hdr_center),
        Paragraph("Description", hdr_style),
        Paragraph("Qty", hdr_center),
        Paragraph("Unit Price", hdr_right),
        Paragraph("Amount", hdr_right),
    ]]

    right_style = styles["Normal"].clone("TableRight")
    right_style.alignment = 2

    center_style = styles["Normal"].clone("TableCenter")
    center_style.alignment = 1

    for idx, item in enumerate(invoice.line_items, start=1):
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
            Paragraph(str(idx), center_style),
            Paragraph(item.description, styles["Normal"]),
            Paragraph(qty_str, center_style),
            Paragraph(formatted_price, right_style),
            Paragraph(formatted_amount, right_style),
        ])

    items_table = Table(
        table_data,
        colWidths=[30, 260, 50, 100, 100],
        repeatRows=1,
    )

    t_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]

    # Alternating row colors
    for r in range(1, len(table_data)):
        bg = colors.HexColor("#f8fafc") if r % 2 == 1 else colors.white
        t_style.append(("BACKGROUND", (0, r), (-1, r), bg))

    items_table.setStyle(TableStyle(t_style))
    story.append(items_table)
    story.append(Spacer(1, 10))

    # 4. Totals summary
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
        rate_label = f" ({int(invoice.tax_rate * 100)}%)" if invoice.tax_rate else ""
        summary_rows.append([
            Paragraph(f"<b>Tax{rate_label}:</b>", right_style),
            Paragraph(tax_str, right_style),
        ])

    total_str = format_currency_amount(
        invoice.total,
        locale=invoice.locale,
        currency_symbol=invoice.currency_symbol,
        symbol_position=invoice.currency_position,
    )
    summary_rows.append([
        Paragraph("<b><font size='11' color='#0284c7'>Total:</font></b>", right_style),
        Paragraph(f"<b><font size='11' color='#0284c7'>{total_str}</font></b>", right_style),
    ])

    summary_table = Table(summary_rows, colWidths=[400, 140])
    summary_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#0284c7")),
        ])
    )
    story.append(summary_table)

    doc.build(story, canvasmaker=NumberedCanvas)
