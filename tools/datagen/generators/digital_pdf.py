"""Digital PDF invoice dataset generator."""

import datetime
from decimal import Decimal, ROUND_HALF_UP
import random
from typing import List, Tuple

from tools.datagen.config import (
    DEV_LAYOUTS,
    TEST_LAYOUTS,
    DEV_SUPPLIERS,
    TEST_SUPPLIERS,
    CUSTOMERS,
    CATALOG_ITEMS,
)
from tools.datagen.models import InvoiceData, LineItem


def round_money(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_date_for_layout(iso_date: str, layout: str) -> str:
    dt = datetime.date.fromisoformat(iso_date)
    if layout == "modern_clean":
        return dt.strftime("%Y-%m-%d")
    elif layout == "classic_corporate":
        return dt.strftime("%d/%m/%Y")
    elif layout == "compact_slip":
        return dt.strftime("%d-%b-%Y")
    elif layout == "bold_banner":
        return dt.strftime("%B %d, %Y")
    elif layout == "minimalist_sidebar":
        return dt.strftime("%m/%d/%Y")
    elif layout == "international_multilingual":
        return dt.strftime("%d.%m.%Y")
    return dt.strftime("%Y-%m-%d")


def build_digital_pdf_dataset(rng: random.Random) -> List[InvoiceData]:
    """Generate deterministic digital PDF invoices partitioned into dev and test splits."""
    invoices: List[InvoiceData] = []
    doc_counter = 1

    # Base dates to pick from
    base_dates = [
        "2026-01-15",
        "2026-01-28",
        "2026-02-10",
        "2026-02-22",
        "2026-03-05",
        "2026-03-14",
        "2026-03-29",
        "2026-04-12",
        "2026-04-25",
        "2026-05-08",
    ]

    # DEV DATASET: 22 invoices across 11 suppliers and 4 dev layouts
    # We assign 2 invoices per dev supplier
    for supp_idx, supplier in enumerate(DEV_SUPPLIERS):
        for variant in range(2):
            doc_id = f"syn_{doc_counter:03d}"
            doc_counter += 1

            # Cycle layouts
            layout = DEV_LAYOUTS[(supp_idx * 2 + variant) % len(DEV_LAYOUTS)]

            iso_date = base_dates[(supp_idx + variant * 3) % len(base_dates)]
            dt = datetime.date.fromisoformat(iso_date)
            due_iso = (dt + datetime.timedelta(days=30)).isoformat()
            display_date = format_date_for_layout(iso_date, layout)

            inv_num = f"INV-2026-D{doc_counter-1:03d}"

            # Customer selection (some missing customer name on purpose)
            omit_customer = (supp_idx == 7 and variant == 1)  # Horizon Peak direct sale
            if omit_customer:
                cust_name = None
                cust_addr = ""
                cust_tax = None
            else:
                cust = CUSTOMERS[(supp_idx + variant * 2) % len(CUSTOMERS)]
                cust_name = cust["name"]
                cust_addr = cust["address"]
                cust_tax = cust.get("tax_id")

            # Line items count: single page vs multi-page
            # Kestrel Global Freight Solutions (supp_idx 10, variant 1) -> 25 items for multi-page test
            if supp_idx == 10 and variant == 1:
                item_count = 25
                notes = "Multi-page digital PDF test (25 line items)"
            elif supp_idx == 2 and variant == 0:
                item_count = 3
                notes = "Ambiguous currency symbol bare $"
            elif supp_idx == 9 and variant == 1:
                item_count = 2
                notes = "Tax exempt / omitted tax"
            elif supp_idx == 3 and variant == 0:
                item_count = 1
                notes = "Single line item European number formatting"
            else:
                item_count = [1, 2, 4, 6, 8, 12, 16][(supp_idx + variant) % 7]
                notes = f"Digital PDF {layout} layout"

            # Select line items deterministically
            line_items: List[LineItem] = []
            for i in range(item_count):
                catalog_item = CATALOG_ITEMS[(supp_idx * 3 + variant * 5 + i) % len(CATALOG_ITEMS)]
                desc = catalog_item[0]
                price = Decimal(catalog_item[1])
                # JPY price scaling if currency is JPY
                if supplier["currency"] == "JPY":
                    price = round_money(price * Decimal("150.00"))

                qty = Decimal(str(((supp_idx + variant + i) % 5) + 1))
                amount = round_money(qty * price)
                line_items.append(LineItem(
                    description=desc,
                    quantity=qty,
                    unit_price=price,
                    amount=amount,
                ))

            subtotal = sum((item.amount for item in line_items), Decimal("0.00"))

            # Tax handling
            omit_tax = (supp_idx == 9 and variant == 1)
            if omit_tax:
                tax_rate = None
                tax = None
                total = subtotal
            else:
                tax_rate = Decimal(supplier["default_tax_rate"])
                tax = round_money(subtotal * tax_rate)
                total = subtotal + tax

            # Currency handling (ambiguous bare '$' check)
            is_ambiguous = supplier.get("ambiguous_currency", False)
            curr = None if is_ambiguous else supplier["currency"]

            inv = InvoiceData(
                id=doc_id,
                filename=f"{doc_id}.pdf",
                invoice_number=inv_num,
                invoice_date=iso_date,
                due_date=due_iso,
                supplier_name=supplier["name"],
                supplier_address=supplier["address"],
                supplier_email=supplier["email"],
                supplier_phone=supplier["phone"],
                supplier_tax_id=supplier["tax_id"],
                customer_name=cust_name,
                customer_address=cust_addr,
                customer_tax_id=cust_tax,
                line_items=line_items,
                subtotal=subtotal,
                tax_rate=tax_rate,
                tax=tax,
                total=total,
                currency=curr,
                currency_symbol=supplier["currency_symbol"],
                currency_position=supplier["currency_position"],
                locale=supplier["locale"],
                layout=layout,
                split="dev",
                quality="digital",
                expected_status="COMPLETED",
                expected_error_code="",
                notes=notes,
                invoice_count=1,
                display_date=display_date,
            )
            invoices.append(inv)

    # TEST DATASET: 10 invoices across 5 test suppliers and 2 test layouts
    # 2 invoices per test supplier
    for supp_idx, supplier in enumerate(TEST_SUPPLIERS):
        for variant in range(2):
            doc_id = f"syn_{doc_counter:03d}"
            doc_counter += 1

            # Alternate between test layouts
            layout = TEST_LAYOUTS[(supp_idx + variant) % len(TEST_LAYOUTS)]

            iso_date = base_dates[(supp_idx + variant * 4 + 2) % len(base_dates)]
            dt = datetime.date.fromisoformat(iso_date)
            due_iso = (dt + datetime.timedelta(days=30)).isoformat()
            display_date = format_date_for_layout(iso_date, layout)

            inv_num = f"INV-2026-T{doc_counter-1:03d}"

            # Customer selection
            omit_customer = (supp_idx == 3 and variant == 1)
            if omit_customer:
                cust_name = None
                cust_addr = ""
                cust_tax = None
            else:
                cust = CUSTOMERS[(supp_idx + 4 + variant * 3) % len(CUSTOMERS)]
                cust_name = cust["name"]
                cust_addr = cust["address"]
                cust_tax = cust.get("tax_id")

            # Multi-page test in test split (supp_idx 0, variant 1 -> 20 items)
            if supp_idx == 0 and variant == 1:
                item_count = 20
                notes = "Test split multi-page invoice (20 line items)"
            elif supp_idx == 0 and variant == 0:
                item_count = 3
                notes = "Test split ambiguous currency bare $"
            elif supp_idx == 3:  # Orion Precision Optics (JPY)
                item_count = 2 if variant == 0 else 5
                notes = "Test split JPY currency"
            elif supp_idx == 4:  # Pacific Crest (INR)
                item_count = 4
                notes = "Test split INR currency Indian number formatting"
            else:
                item_count = 3 if variant == 0 else 7
                notes = f"Test split {layout} layout"

            line_items = []
            for i in range(item_count):
                catalog_item = CATALOG_ITEMS[(supp_idx * 4 + variant * 3 + i + 10) % len(CATALOG_ITEMS)]
                desc = catalog_item[0]
                price = Decimal(catalog_item[1])
                if supplier["currency"] == "JPY":
                    price = round_money(price * Decimal("150.00"))

                qty = Decimal(str(((supp_idx + variant + i) % 4) + 1))
                amount = round_money(qty * price)
                line_items.append(LineItem(
                    description=desc,
                    quantity=qty,
                    unit_price=price,
                    amount=amount,
                ))

            subtotal = sum((item.amount for item in line_items), Decimal("0.00"))
            tax_rate = Decimal(supplier["default_tax_rate"])
            tax = round_money(subtotal * tax_rate)
            total = subtotal + tax

            is_ambiguous = supplier.get("ambiguous_currency", False)
            curr = None if is_ambiguous else supplier["currency"]

            inv = InvoiceData(
                id=doc_id,
                filename=f"{doc_id}.pdf",
                invoice_number=inv_num,
                invoice_date=iso_date,
                due_date=due_iso,
                supplier_name=supplier["name"],
                supplier_address=supplier["address"],
                supplier_email=supplier["email"],
                supplier_phone=supplier["phone"],
                supplier_tax_id=supplier["tax_id"],
                customer_name=cust_name,
                customer_address=cust_addr,
                customer_tax_id=cust_tax,
                line_items=line_items,
                subtotal=subtotal,
                tax_rate=tax_rate,
                tax=tax,
                total=total,
                currency=curr,
                currency_symbol=supplier["currency_symbol"],
                currency_position=supplier["currency_position"],
                locale=supplier["locale"],
                layout=layout,
                split="test",
                quality="digital",
                expected_status="COMPLETED",
                expected_error_code="",
                notes=notes,
                invoice_count=1,
                display_date=display_date,
            )
            invoices.append(inv)

    return invoices
