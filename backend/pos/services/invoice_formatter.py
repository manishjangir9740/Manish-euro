"""Invoice formatting service producing clear, compliant, printable receipts.

Formats text invoices aligned with Indian GST requirements and sample_invoice.txt.
"""

from typing import Any, Dict, List, Optional
from pos.domain.money import Money
from pos.domain.models import Cart, Customer, StoreLocation


class InvoiceFormatter:
    """Formats compliant GST tax invoices for screen display or thermal printing."""

    @classmethod
    def format_invoice(
        cls,
        invoice_no: str,
        date_str: str,
        store: StoreLocation,
        customer: Customer,
        cart: Cart,
        staff_id: str,
        channel: str,
        payment_method: str,
        terminal_ref: str,
        shopify_order_num: Optional[int] = None,
        shopify_order_id: Optional[int] = None,
        applied_offers: Optional[List[str]] = None,
        rx_id: Optional[str] = None,
    ) -> str:
        width = 104
        sep_double = "=" * width
        sep_single = "-" * width

        lines: List[str] = [
            sep_double,
            "ELUNO".center(width),
            f"{store.name} · {store.name.replace('Eluno ', '')}, Bengaluru".center(width),
            "TAX INVOICE".center(width),
            sep_double,
            f"Invoice no : {invoice_no:<30} Date        : {date_str}",
            f"Store      : {store.store_code:<30} Staff       : {staff_id}",
            f"Customer   : {customer.full_name:<30} Phone       : {customer.phone}",
            f"Rx on file : {rx_id or 'N/A':<30} Channel     : {channel}",
            sep_single,
            f"{'#':<3}{'Description':<38}{'HSN':<10}{'Qty':>4}{'MRP(incl)':>11}{'Discount':>10}{'Taxable':>11}{'CGST':>13}{'SGST':>13}{'Total':>11}",
            sep_single,
        ]

        total_mrp = Money.zero()
        total_disc = Money.zero()
        total_taxable = Money.zero()
        total_cgst = Money.zero()
        total_sgst = Money.zero()
        total_final = Money.zero()

        for idx, item in enumerate(cart.items, 1):
            desc = item.variant.display_name
            if item.rx:
                desc += f", Rx {item.rx.rx_id}"
            if len(desc) > 36:
                desc = desc[:33] + "..."

            mrp = item.line_subtotal
            disc = item.discount
            taxable = item.taxable_amount
            gross = item.gross_amount

            cgst_line = item.tax_lines[0] if len(item.tax_lines) > 0 else None
            sgst_line = item.tax_lines[1] if len(item.tax_lines) > 1 else None

            cgst_rate_str = f"{cgst_line.rate_bps / 100:g}%" if cgst_line else "0%"
            sgst_rate_str = f"{sgst_line.rate_bps / 100:g}%" if sgst_line else "0%"

            cgst_str = f"{cgst_rate_str:>4} {cgst_line.price.to_decimal():>7}" if cgst_line else "   0.00"
            sgst_str = f"{sgst_rate_str:>4} {sgst_line.price.to_decimal():>7}" if sgst_line else "   0.00"

            total_mrp += mrp
            total_disc += disc
            total_taxable += taxable
            if cgst_line:
                total_cgst += cgst_line.price
            if sgst_line:
                total_sgst += sgst_line.price
            total_final += gross

            row = (
                f"{idx:<3}"
                f"{desc:<38}"
                f"{item.variant.hsn:<10}"
                f"{item.quantity:>4}"
                f"{mrp.to_decimal():>11}"
                f"{disc.to_decimal():>10}"
                f"{taxable.to_decimal():>11}"
                f"{cgst_str:>13}"
                f"{sgst_str:>13}"
                f"{gross.to_decimal():>11}"
            )
            lines.append(row)

        lines.append(sep_single)
        totals_row = (
            f"{'':<3}"
            f"{'TOTAL':<38}"
            f"{'':<10}"
            f"{'':>4}"
            f"{total_mrp.to_decimal():>11}"
            f"{total_disc.to_decimal():>10}"
            f"{total_taxable.to_decimal():>11}"
            f"{total_cgst.to_decimal():>13}"
            f"{total_sgst.to_decimal():>13}"
            f"{total_final.to_decimal():>11}"
        )
        lines.append(totals_row)
        lines.append(sep_double)

        offers_str = ", ".join(applied_offers) if applied_offers else "None"
        lines.append(f"Offers applied : {offers_str}")
        lines.append(f"Payment        : {payment_method.upper()} {total_final.format_inr()}  ref {terminal_ref}")
        lines.append(f"Amount in words: {total_final.to_words()}")
        if shopify_order_num and shopify_order_id:
            lines.append(f"Shopify ref    : #{shopify_order_num} (order {shopify_order_id})")
        lines.append(sep_single)
        lines.append(
            "Prices are inclusive of GST. Intra-state supply: CGST + SGST. Taxable value = inclusive price less tax, per line."
        )
        lines.append(
            "Lenses are made to order against the prescription on file and are not returnable once dispensed; frames may be returned within 7 days."
        )
        lines.append(sep_double)

        return "\n".join(lines)
