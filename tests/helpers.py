"""Shared builders for tests. Nothing here touches the network or the real state/ directory."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from pos.domain.audit import AuditLogger
from pos.domain.invoice_series import InvoiceSeriesManager
from pos.domain.models import (
    Cart, CartItem, Customer, EyeRx, LensLimits, OrderLine, OrderRecord, Prescription,
    StoreLocation, Variant,
)
from pos.domain.money import Money
from pos.domain.till import TillSessionManager
from pos.services.outbox import BillOutbox
from pos.services.pos_service import PosService

HSR = StoreLocation(70000002, "Eluno HSR Layout", "HSR", "ELU/HSR/FY26/", "29", "store")


def frame(price="10998.00", vid=91000003):
    return Variant(id=vid, product_id=1, sku="FR-0003", title="Tortoise", price=Money.from_decimal(price),
                   inventory_item_id=92000003, line_type="frame", hsn="90031900", product_title="Atelier Rectangle 03")


def lens(price="9499.00", ltype="progressive", index=1.6, coating="blue_cut", vid=91000083,
         limits=LensLimits(-8.0, 6.0, 4.0, True, 0.75, 3.0)):
    return Variant(id=vid, product_id=2, sku="LN-0043", title=coating, price=Money.from_decimal(price),
                   inventory_item_id=None, line_type="lens", hsn="90015000", lens_type=ltype, index=index,
                   coating=coating, rx_limits=limits, product_title=f"{ltype} {index}")


def customer(tags=(), cid=80001005):
    return Customer(cid, "Karthik", "Reddy", "+919000000005", list(tags), Money.zero())


def rx(cid=80001005, od=(-3.25, 0.0, None, 2.5), os=(-3.5, 0.0, None, 2.5), source="in_store",
       date="2026-07-10", valid_until="2027-07-10", rx_id="RX5007"):
    return Prescription(rx_id, cid, "+919000000005", date, source, "S107",
                        EyeRx(*od), EyeRx(*os), {"binocular": 60}, valid_until)


def pair_cart(tags=(), lens_kwargs=None, with_rx=None):
    c = Cart(customer=customer(tags))
    c.add_item(CartItem(variant=frame(), pair_ref="1"))
    c.add_item(CartItem(variant=lens(**(lens_kwargs or {})), pair_ref="1", rx=with_rx or rx(),
                        lens_config="progressive/1.6/blue_cut"))
    return c


def order_record(payment="upi", refunds=(), cancelled=False, order_id=95000001):
    """Order #1001 from the seed: frame 10998.00 (tax 1677.66) + lens 9499.00 less 1424.85 (tax 384.48)."""
    lines = [
        OrderLine(96000001, "FR-0003", "frame", 1, Money(1099800), Money(0), Money(167766)),
        OrderLine(96000002, "LN-0043", "lens", 1, Money(949900), Money(142485), Money(38448), "RX5007"),
    ]
    return OrderRecord(
        order_id=order_id, order_number=1001, name="#1001", created_at="2026-10-02T12:30:00+05:30",
        location_id=70000002, customer_id=80001005, invoice_no="ELU/HSR/FY26/00001", store_code="HSR",
        channel="whatsapp_booked", staff_id="S105", payment_method=payment, subtotal=Money(2049700),
        discounts=Money(142485), tax=Money(206214), total=Money(1907215), lines=lines,
        sale_transaction_id=97000001, sale_authorization="chg_1", captured=Money(1907215),
        refunds=list(refunds), cancelled=cancelled,
    )


def make_service(tmp: Path, shopify=None, terminal=None, smt=None):
    shopify = shopify or MagicMock()
    shopify.get_location_by_code.return_value = HSR
    shopify.last_document_numbers.return_value = (0, 0)
    return PosService(
        shopify_adapter=shopify, smt_adapter=smt or MagicMock(), terminal_adapter=terminal or MagicMock(),
        invoice_manager=InvoiceSeriesManager(tmp / "inv.json"), till_manager=TillSessionManager(tmp / "till.json"),
        audit_logger=AuditLogger(tmp / "audit.json"), outbox=BillOutbox(tmp / "outbox.json"),
    )


def tmpdir():
    d = tempfile.TemporaryDirectory()
    return d, Path(d.name)
