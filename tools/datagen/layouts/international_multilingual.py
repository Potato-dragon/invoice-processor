"""Layout: International Multilingual (Test Layout 2)
Bilingual European invoice with French/English labels, European number formatting, and elegant styling.
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


def render_international_multilingual(invoice: InvoiceData, output_path: str) -> None:
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

    # 1. Header: Supplier details & Bilingual Invoice Title
    supp_lines = []
    if invoice.supplier_name:
        supp_lines.append(f"<b><font size='13' color='#4c0519'>{invoice.supplier_name}</font></b>")
    if invoice.supplier_address:
        supp_lines.append(invoice.supplier_address)
    if invoice.supplier_email or invoice.supplier_phone:
        supp_lines.append(f"Courriel: {invoice.supplier_email} • Tél: {invoice.supplier_phone}")
    if invoice.supplier_tax_id:
        supp_lines.append(f"N° TVA Intracommunautaire: {invoice.supplier_tax_id}")

    left_header = Paragraph("<br/>".join(supp_lines), styles["Normal"])

    meta_lines = [
        "<font size='18' color='#4c0519'><b>FACTURE / INVOICE</b></font>",
        f"<b>Facture N° / Invoice No:</b> {invoice.invoice_number}",
        f"<b>Date d'émission / Date:</b> {invoice.display_date}",
    ]
    if invoice.due_date:
        meta_lines.append(f"<b>Échéance / Due:</b> {invoice.due_date}")

    meta_style = styles["Normal"].clone("IntlMeta")
    meta_style.alignment = 2

    header_table = Table(
        [[left_header, Paragraph("<br/>".join(meta_lines), meta_style)]],
        colWidths=[310, 230],
    )
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(header_table)
    story.append(Spacer(1, 15))

    # 2. Destinataire / Bill To
    if invoice.customer_name:
        cust_lines = [
            "<font size='9' color='#4c0519'><b>DESTINATAIRE / BILL TO:</b></font>",
            f"<b>{invoice.customer_name}</b>",
        ]
        if invoice.customer_address:
            cust_lines.append(invoice.customer_address)
        if invoice.customer_tax_id:
            cust_lines.append(f"N° TVA Client: {invoice.customer_tax_id}")

        cust_p = Paragraph("<br/>".join(cust_lines), styles["Normal"])
        cust_table = Table([[cust_p]], colWidths=[540])
        cust_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff1f2")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#fecdd3")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ])
        )
        story.append(cust_table)
        story.append(Spacer(1, 15))

    # 3. Bilingual Items Table
    right_style = styles["Normal"].clone("IntlRight")
    right_style.alignment = 2

    center_style = styles["Normal"].clone("IntlCenter")
    center_style.alignment = 1

    table_data = [[
        Paragraph("<b><font color='white'>Désignation / Description</font></b>", styles["Normal"]),
        Paragraph("<b><font color='white'>Qté / Qty</font></b>", center_style),
        Paragraph("<b><font color='white'>Prix Unit. / Rate</font></b>", right_style),
        Paragraph("<b><font color='white'>Montant HT / Total</font></b>", right_style),
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
        colWidths=[290, 60, 95, 95],
        repeatRows=1,
    )
    items_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4c0519")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#ffe4e6")),
        ])
    )
    story.append(items_table)
    story.append(Spacer(1, 10))

    # 4. Bilingual Summary
    summary_rows = []
    if invoice.subtotal is not None:
        sub_str = format_currency_amount(
            invoice.subtotal,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        summary_rows.append([
            Paragraph("<b>Total Hors Taxes (HT):</b>", right_style),
            Paragraph(sub_str, right_style),
        ])

    if invoice.tax is not None:
        tax_str = format_currency_amount(
            invoice.tax,
            locale=invoice.locale,
            currency_symbol=invoice.currency_symbol,
            symbol_position=invoice.currency_position,
        )
        rate_str = f" ({int(invoice.tax_rate * 100)}%)" if invoice.tax_rate else ""
        summary_rows.append([
            Paragraph(f"<b>TVA / Tax{rate_str}:</b>", right_style),
            Paragraph(tax_str, right_style),
        ])

    total_str = format_currency_amount(
        invoice.total,
        locale=invoice.locale,
        currency_symbol=invoice.currency_symbol,
        symbol_position=invoice.currency_position,
    )
    summary_rows.append([
        Paragraph("<b><font size='10' color='#4c0519'>Total Toutes Taxes Comprises (TTC):</font></b>", right_style),
        Paragraph(f"<b><font size='10' color='#4c0519'>{total_str}</font></b>", right_style),
    ])

    summary_table = Table(summary_rows, colWidths=[380, 160])
    summary_table.setStyle(
        TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#4c0519")),
        ])
    )
    story.append(summary_table)

    doc.build(story, canvasmaker=NumberedCanvas)
