"""Layout: Classic Corporate (Dev Layout 2)
Traditional corporate invoice with centered header, boxed grid lines, and formal serif/sans typography.
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


def render_classic_corporate(invoice: InvoiceData, output_path: str) -> None:
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

    # 1. Centered header with company details
    center_style = styles["Normal"].clone("CenterCompany")
    center_style.alignment = 1

    company_lines = []
    if invoice.supplier_name:
        company_lines.append(f"<b><font size='16'>{invoice.supplier_name.upper()}</font></b>")
    if invoice.supplier_address:
        company_lines.append(invoice.supplier_address)
    if invoice.supplier_email or invoice.supplier_phone:
        company_lines.append(f"Email: {invoice.supplier_email} | Tel: {invoice.supplier_phone}")
    if invoice.supplier_tax_id:
        company_lines.append(f"VAT / Tax Reg: {invoice.supplier_tax_id}")

    story.append(Paragraph("<br/>".join(company_lines), center_style))
    story.append(Spacer(1, 10))

    # Double divider bar
    bar_data = [[
        Paragraph("<b><font size='12'>COMMERCIAL INVOICE</font></b>", center_style)
    ]]
    bar_table = Table(bar_data, colWidths=[540])
    bar_table.setStyle(
        TableStyle([
            ("LINEABOVE", (0, 0), (-1, -1), 1.5, colors.HexColor("#1e293b")),
            ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor("#1e293b")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(bar_table)
    story.append(Spacer(1, 12))

    # 2. Two boxes: Sold To (left) vs Invoice Details (right)
    sold_to_lines = ["<b>CUSTOMER INFORMATION</b>", "<b>Sold To:</b>"]
    if invoice.customer_name:
        sold_to_lines.append(f"<b>{invoice.customer_name}</b>")
        if invoice.customer_address:
            sold_to_lines.append(invoice.customer_address)
        if invoice.customer_tax_id:
            sold_to_lines.append(f"Client Ref: {invoice.customer_tax_id}")
    else:
        sold_to_lines.append("<i>Direct / Counter Sale</i>")

    meta_lines = [
        "<b>INVOICE DETAILS</b>",
        f"<b>Invoice No.:</b> {invoice.invoice_number}",
        f"<b>Date of Issue:</b> {invoice.display_date}",
    ]
    if invoice.due_date:
        meta_lines.append(f"<b>Payment Due:</b> {invoice.due_date}")

    info_data = [[
        Paragraph("<br/>".join(sold_to_lines), styles["Normal"]),
        Paragraph("<br/>".join(meta_lines), styles["Normal"]),
    ]]
    info_table = Table(info_data, colWidths=[270, 270])
    info_table.setStyle(
        TableStyle([
            ("BOX", (0, 0), (0, 0), 1, colors.HexColor("#94a3b8")),
            ("BOX", (1, 0), (1, 0), 1, colors.HexColor("#94a3b8")),
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fafc")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f8fafc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(info_table)
    story.append(Spacer(1, 15))

    # 3. Grid Table for items
    table_data = [[
        Paragraph("<b>Line #</b>", center_style),
        Paragraph("<b>Item Description</b>", styles["Normal"]),
        Paragraph("<b>Quantity</b>", center_style),
        Paragraph("<b>Rate</b>", styles["Normal"]),
        Paragraph("<b>Line Total</b>", styles["Normal"]),
    ]]

    right_style = styles["Normal"].clone("RightNum")
    right_style.alignment = 2

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

    grid_table = Table(
        table_data,
        colWidths=[45, 245, 55, 95, 100],
        repeatRows=1,
    )
    grid_table.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    story.append(grid_table)
    story.append(Spacer(1, 10))

    # 4. Boxed summary at bottom
    summary_rows = []
    if invoice.subtotal is not None:
        sub_str = format_currency_amount(
            invoice.subtotal,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        summary_rows.append([
            Paragraph("<b>Net Amount:</b>", right_style),
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
            Paragraph("<b>Sales Tax:</b>", right_style),
            Paragraph(tax_str, right_style),
        ])

    total_str = format_currency_amount(
        invoice.total,
        locale=invoice.locale,
        currency_symbol=invoice.currency_symbol,
        symbol_position=invoice.currency_position,
    )
    summary_rows.append([
        Paragraph("<b><font size='10'>Total Due:</font></b>", right_style),
        Paragraph(f"<b><font size='10'>{total_str}</font></b>", right_style),
    ])

    summary_table = Table(summary_rows, colWidths=[390, 150])
    summary_table.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(summary_table)

    doc.build(story, canvasmaker=NumberedCanvas)
