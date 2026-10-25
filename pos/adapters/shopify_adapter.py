"""Shopify Admin REST API adapter (the anti-corruption layer).

This is the only module that knows Shopify's shapes. It translates:
- Shopify customers / locations / variants  -> domain Customer / StoreLocation / Variant
- domain Cart + invoice metadata           -> Shopify order payload (decimal-string money)
- Shopify orders / refunds                 -> domain OrderRecord / RefundRecord
- domain RefundPlan                        -> Shopify refund payload (restock_type, location_id)

Replacing Shopify means writing another class with the same public methods.

Idempotency: Shopify order create is not idempotent. Our key is the per-store invoice
number, written to note_attributes (and tags). Before retrying a create whose outcome
is unknown, the adapter looks the invoice number up and returns the existing order.
"""

import json
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from pos.config import SHOPIFY_API_BASE
from pos.adapters.http_client import AmbiguousWriteError, HttpStatusError, ResilientHttpClient
from pos.domain.money import Money
from pos.domain.models import (
    AppliedOffer,
    Cart,
    Customer,
    LensLimits,
    ManualDiscount,
    OrderLine,
    OrderRecord,
    RefundRecord,
    StoreLocation,
    Variant,
)
from pos.domain.refunds import RefundPlan

GATEWAYS = {"cash": "cash", "upi": "razorpay_terminal", "card": "razorpay_terminal"}


def _attrs(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {a.get("name"): a.get("value") for a in items or []}


class ShopifyAdapter:
    """Adapts Eluno POS domain operations to Shopify REST Admin API."""

    def __init__(self, base_url: str = SHOPIFY_API_BASE, client: Optional[ResilientHttpClient] = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or ResilientHttpClient()
        self._locations: Optional[List[StoreLocation]] = None
        self._products: Optional[Dict[int, Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Reads: customers, locations, catalog, stock
    # ------------------------------------------------------------------
    def search_customer_by_phone(self, phone: str) -> Optional[Customer]:
        """Search Shopify for customer by phone number."""
        encoded = urllib.parse.quote(f"phone:{phone}")
        data = self.client.get(f"{self.base_url}/customers/search.json?query={encoded}")
        customers = data.get("customers", [])
        if not customers:
            return None
        c = customers[0]
        raw_tags = c.get("tags", "")
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()] if isinstance(raw_tags, str) else list(raw_tags)
        return Customer(
            id=c["id"],
            first_name=c.get("first_name", ""),
            last_name=c.get("last_name", ""),
            phone=c.get("phone", phone),
            tags=tags,
            total_spent=Money.from_decimal(c.get("total_spent", "0.00")),
        )

    def get_locations(self) -> List[StoreLocation]:
        """Fetch all locations and map to domain StoreLocation entities (cached)."""
        if self._locations is None:
            data = self.client.get(f"{self.base_url}/locations.json")
            self._locations = []
            for loc in data.get("locations", []):
                eluno = loc.get("eluno", {})
                code = eluno.get("store_code", "")
                self._locations.append(StoreLocation(
                    id=loc["id"],
                    name=loc["name"],
                    store_code=code,
                    invoice_prefix=eluno.get("invoice_prefix") or f"ELU/{code}/FY26/",
                    state_code=eluno.get("state_code", "29"),
                    kind=eluno.get("kind", "store"),
                ))
        return self._locations

    def get_location_by_code(self, store_code: str) -> StoreLocation:
        for loc in self.get_locations():
            if loc.store_code.upper() == store_code.upper():
                if loc.kind != "store":
                    raise ValueError(f"Location '{store_code}' is a {loc.kind}, not a billing store")
                return loc
        raise ValueError(f"Store location with code '{store_code}' not found")

    def get_location_by_id(self, location_id: int) -> StoreLocation:
        for loc in self.get_locations():
            if loc.id == location_id:
                return loc
        raise ValueError(f"Store location with id {location_id} not found")

    def _catalog(self) -> Dict[int, Dict[str, Any]]:
        """variant_id -> {variant, product} for the whole catalog (cached)."""
        if self._products is None:
            self._products = {}
            data = self.client.get(f"{self.base_url}/products.json?limit=250")
            for p in data.get("products", []):
                for v in p.get("variants", []):
                    self._products[v["id"]] = {"variant": v, "product": p}
        return self._products

    @staticmethod
    def _to_variant(v: Dict[str, Any], product: Optional[Dict[str, Any]]) -> Variant:
        eluno = v.get("eluno", {})
        lim = eluno.get("rx_limits")
        rx_limits = None
        if lim:
            rx_limits = LensLimits(
                sph_min=float(lim["sph_min"]),
                sph_max=float(lim["sph_max"]),
                cyl_abs_max=float(lim["cyl_abs_max"]),
                add_required=bool(lim.get("add_required", False)),
                add_min=float(lim["add_min"]) if lim.get("add_min") is not None else None,
                add_max=float(lim["add_max"]) if lim.get("add_max") is not None else None,
            )
        return Variant(
            id=v["id"],
            product_id=v["product_id"],
            sku=v["sku"],
            title=v["title"],
            price=Money.from_decimal(v["price"]),
            inventory_item_id=v.get("inventory_item_id"),
            line_type=eluno.get("line_type", "frame"),
            hsn=eluno["hsn"],
            category=eluno.get("category"),
            lens_type=eluno.get("lens_type"),
            index=eluno.get("index"),
            coating=eluno.get("coating"),
            rx_limits=rx_limits,
            lab_tat_days=eluno.get("lab_tat_days"),
            rx_able=eluno.get("rx_able", True),
            product_title=(product or {}).get("title"),
            active=(product or {}).get("status", "active") == "active",
        )

    def get_variant(self, variant_id: int) -> Variant:
        """Fetch variant by ID and map to domain Variant."""
        hit = self._catalog().get(variant_id)
        if hit:
            return self._to_variant(hit["variant"], hit["product"])
        data = self.client.get(f"{self.base_url}/variants/{variant_id}.json")
        v = data.get("variant")
        if not v:
            raise ValueError(f"Variant {variant_id} not found")
        return self._to_variant(v, None)

    def list_lens_variants(self) -> List[Variant]:
        """The lens matrix (type x index x coating) as domain variants."""
        return [
            self._to_variant(h["variant"], h["product"])
            for h in self._catalog().values()
            if h["variant"].get("eluno", {}).get("line_type") == "lens"
        ]

    def list_frame_variants(self) -> List[Variant]:
        """Active frames, as domain variants."""
        return [
            self._to_variant(h["variant"], h["product"])
            for h in self._catalog().values()
            if h["variant"].get("eluno", {}).get("line_type") == "frame" and h["product"].get("status") == "active"
        ]

    def check_stock(self, inventory_item_id: int, location_id: int) -> int:
        """Check available stock for an item at a specific store location."""
        url = f"{self.base_url}/inventory_levels.json?inventory_item_ids={inventory_item_id}&location_ids={location_id}"
        levels = self.client.get(url).get("inventory_levels", [])
        return int(levels[0].get("available", 0)) if levels else 0

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def build_order_payload(
        self,
        cart: Cart,
        location: StoreLocation,
        invoice_no: str,
        channel: str,
        staff_id: str,
        payment_method: str,
        charge_id: Optional[str],
        applied_offers: List[AppliedOffer],
        manual: Optional[ManualDiscount] = None,
    ) -> Dict[str, Any]:
        """Translate a priced domain cart into a Shopify order create payload."""
        if cart.customer is None:
            raise ValueError("Customer required")
        line_items = []
        for item in cart.items:
            props = [
                {"name": "line_type", "value": item.variant.line_type},
                {"name": "hsn", "value": item.variant.hsn},
                {"name": "pair_ref", "value": str(item.pair_ref)},
            ]
            if item.variant.line_type == "lens":
                if item.rx:
                    props.append({"name": "rx_id", "value": item.rx.rx_id})
                    rx_dump = json.dumps({
                        "od": {"sph": item.rx.od.sph, "cyl": item.rx.od.cyl, "axis": item.rx.od.axis, "add": item.rx.od.add},
                        "os": {"sph": item.rx.os.sph, "cyl": item.rx.os.cyl, "axis": item.rx.os.axis, "add": item.rx.os.add},
                        "pd": item.rx.pd.get("binocular"),
                    }, separators=(",", ":"))
                    props.append({"name": "rx", "value": rx_dump})
                if item.lens_config:
                    props.append({"name": "lens_config", "value": item.lens_config})

            line_items.append({
                "variant_id": item.variant.id,
                "quantity": item.quantity,
                "price": item.variant.price.to_decimal(),
                "total_discount": item.discount.to_decimal(),
                "tax_lines": [
                    {"title": tl.title, "rate": tl.rate, "price": tl.price.to_decimal()}
                    for tl in item.tax_lines
                ],
                "discount_allocations": [
                    {"amount": da.amount.to_decimal(), "discount_application_index": da.discount_application_index}
                    for da in item.discount_allocations
                ],
                "properties": props,
            })

        discount_apps = [
            {
                "type": "manual",
                "title": ao.offer_id,
                "description": ao.name,
                "value": ao.amount.to_decimal(),
                "value_type": "fixed_amount",
                "allocation_method": "each",
                "target_selection": "explicit",
                "target_type": "line_item",
            }
            for ao in applied_offers
        ]

        note_attributes = [
            {"name": "invoice_no", "value": invoice_no},
            {"name": "store_code", "value": location.store_code},
            {"name": "channel", "value": channel},
            {"name": "staff_id", "value": staff_id},
            {"name": "payment_method", "value": payment_method},
        ]
        if manual is not None and any(ao.offer_id == "MANAGER_OVERRIDE" for ao in applied_offers):
            note_attributes += [
                {"name": "discount_reason_code", "value": manual.reason_code},
                {"name": "discount_approver_id", "value": manual.approver_id},
            ]

        transactions = []
        if cart.total_price.paise > 0:
            transactions.append({
                "kind": "sale",
                "status": "success",
                "gateway": GATEWAYS.get(payment_method, "razorpay_terminal"),
                "amount": cart.total_price.to_decimal(),
                "authorization": charge_id,
            })

        return {
            "order": {
                "taxes_included": True,
                "location_id": location.id,
                "inventory_behaviour": "decrement_obeying_policy",
                "source_name": "eluno-pos",
                "customer": {"id": cart.customer.id},
                "tags": f"pos,{channel},invoice:{invoice_no}",
                "note_attributes": note_attributes,
                "line_items": line_items,
                "discount_applications": discount_apps,
                "transactions": transactions,
            }
        }

    def submit_order(
        self,
        payload: Dict[str, Any],
        invoice_no: str,
        location_id: int,
        check_existing_first: bool = False,
        max_attempts: int = 4,
    ) -> OrderRecord:
        """Create the order exactly once, keyed by invoice_no.

        429s are retried inside the HTTP client (never processed). If the outcome of a
        create is unknown (timeout / connection drop / 5xx), look the invoice up before
        trying again, so a create that did land is not repeated.
        """
        if check_existing_first:
            existing = self.find_order_by_invoice_no(invoice_no, location_id)
            if existing:
                return existing
        last_exc: Optional[Exception] = None
        for _ in range(max_attempts):
            try:
                res = self.client.post(f"{self.base_url}/orders.json", payload)
                return self._to_order_record(res["order"])
            except AmbiguousWriteError as exc:
                last_exc = exc
                try:
                    existing = self.find_order_by_invoice_no(invoice_no, location_id)
                except Exception as lookup_exc:  # still offline; caller keeps it in the outbox
                    raise AmbiguousWriteError(exc.url, lookup_exc)
                if existing:
                    return existing
        raise last_exc  # type: ignore[misc]

    def find_order_by_invoice_no(self, invoice_no: str, location_id: int) -> Optional[OrderRecord]:
        """Idempotency lookup. Production: an indexed metafield / tag search instead of a scan."""
        url = f"{self.base_url}/orders.json?location_id={location_id}&status=any&limit=250"
        for o in self.client.get(url).get("orders", []):
            if _attrs(o.get("note_attributes")).get("invoice_no") == invoice_no:
                return self._to_order_record(o)
        return None

    def last_document_numbers(self, location_id: int, prefix: str) -> Tuple[int, int]:
        """Highest invoice and credit-note sequence already recorded for a store: (invoice, credit note)."""
        last_inv = last_cn = 0
        for o in self.orders_for_location(location_id, None, "2999-12-31T00:00:00+00:00"):
            if o.invoice_no and o.invoice_no.startswith(prefix):
                tail = o.invoice_no[len(prefix):]
                if tail.isdigit():
                    last_inv = max(last_inv, int(tail))
            for rf in o.refunds:
                cn = rf.credit_note_no or ""
                if cn.startswith(prefix + "CN/") and cn.rsplit("/", 1)[1].isdigit():
                    last_cn = max(last_cn, int(cn.rsplit("/", 1)[1]))
        return last_inv, last_cn

    def get_order(self, order_id: int) -> OrderRecord:
        try:
            data = self.client.get(f"{self.base_url}/orders/{order_id}.json")
        except HttpStatusError as exc:
            if exc.code == 404:
                raise ValueError(f"Order {order_id} not found in Shopify") from exc
            raise
        o = data.get("order")
        if not o:
            raise ValueError(f"Order {order_id} not found in Shopify")
        return self._to_order_record(o)

    @staticmethod
    def _to_order_record(o: Dict[str, Any]) -> OrderRecord:
        notes = _attrs(o.get("note_attributes"))
        lines = []
        for li in o.get("line_items", []):
            props = _attrs(li.get("properties"))
            lines.append(OrderLine(
                line_id=li["id"],
                sku=li.get("sku", ""),
                line_type=props.get("line_type", "frame"),
                quantity=int(li.get("quantity", 1)),
                price=Money.from_decimal(li.get("price", "0.00")),
                discount=Money.from_decimal(li.get("total_discount", "0.00")),
                tax=sum((Money.from_decimal(t["price"]) for t in li.get("tax_lines", [])), Money.zero()),
                rx_id=props.get("rx_id"),
            ))
        sales = [t for t in o.get("transactions", []) if t.get("kind") == "sale" and t.get("status") == "success"]
        refunds = []
        for rf in o.get("refunds", []):
            refunds.append(RefundRecord(
                refund_id=rf.get("id"),
                created_at=rf.get("created_at", ""),
                amount=sum((Money.from_decimal(t["amount"]) for t in rf.get("transactions", [])
                            if t.get("kind") == "refund"), Money.zero()),
                tax=sum((Money.from_decimal(rl.get("total_tax", "0.00")) for rl in rf.get("refund_line_items", [])),
                        Money.zero()),
                credit_note_no=_attrs(rf.get("note_attributes")).get("credit_note_no"),
                line_ids=[rl["line_item_id"] for rl in rf.get("refund_line_items", [])],
            ))
        return OrderRecord(
            order_id=o["id"],
            order_number=o.get("order_number"),
            name=o.get("name", f"#{o.get('order_number')}"),
            created_at=o.get("created_at", ""),
            location_id=o.get("location_id"),
            customer_id=(o.get("customer") or {}).get("id"),
            invoice_no=notes.get("invoice_no"),
            store_code=notes.get("store_code"),
            channel=notes.get("channel", "walk_in"),
            staff_id=notes.get("staff_id"),
            payment_method=(notes.get("payment_method") or "unknown").lower(),
            subtotal=Money.from_decimal(o.get("subtotal_price", "0.00")),
            discounts=Money.from_decimal(o.get("total_discounts", "0.00")),
            tax=Money.from_decimal(o.get("total_tax", "0.00")),
            total=Money.from_decimal(o.get("total_price", "0.00")),
            lines=lines,
            sale_transaction_id=sales[0]["id"] if sales else None,
            sale_authorization=sales[0].get("authorization") if sales else None,
            captured=sum((Money.from_decimal(t["amount"]) for t in sales), Money.zero()),
            refunds=refunds,
            cancelled=o.get("cancelled_at") is not None,
            parent_invoice_no=notes.get("parent_invoice_no"),
        )

    def orders_for_location(
        self, location_id: int, created_at_min: Optional[str], created_at_max: str
    ) -> List[OrderRecord]:
        """Orders for a location in a window (status=any so refunded/cancelled are included)."""
        q = f"location_id={location_id}&status=any&limit=250&created_at_max={urllib.parse.quote(created_at_max)}"
        if created_at_min:
            q += f"&created_at_min={urllib.parse.quote(created_at_min)}"
        data = self.client.get(f"{self.base_url}/orders.json?{q}")
        return [self._to_order_record(o) for o in data.get("orders", [])]

    # ------------------------------------------------------------------
    # Refunds
    # ------------------------------------------------------------------
    @staticmethod
    def _refund_lines_payload(plan: RefundPlan) -> List[Dict[str, Any]]:
        out = []
        for rl in plan.lines:
            item: Dict[str, Any] = {
                "line_item_id": rl.line_id,
                "quantity": rl.quantity,
                "restock_type": "return" if rl.restock else "no_restock",
            }
            if rl.restock:
                item["location_id"] = rl.location_id
            out.append(item)
        return out

    def calculate_refund(self, plan: RefundPlan) -> Tuple[Money, Money]:
        """Ask Shopify what it would refund: (amount, tax). Read-only, safe to retry."""
        url = f"{self.base_url}/orders/{plan.order.order_id}/refunds/calculate.json"
        res = self.client.post(url, {"refund": {"refund_line_items": self._refund_lines_payload(plan)}}, idempotent=True)
        refund = res.get("refund", {})
        txs = refund.get("transactions", [])
        amount = Money.from_decimal(txs[0]["amount"]) if txs else Money.zero()
        tax = sum((Money.from_decimal(l.get("total_tax", "0.00")) for l in refund.get("refund_line_items", [])), Money.zero())
        return amount, tax

    def create_refund(
        self,
        plan: RefundPlan,
        credit_note_no: str,
        reason_code: str,
        staff_id: str,
        payment_method: str,
    ) -> RefundRecord:
        """Record the refund in Shopify: lines (restock per plan) + refund transaction against the sale."""
        order = plan.order
        payload = {
            "refund": {
                "note": reason_code,
                "note_attributes": [
                    {"name": "credit_note_no", "value": credit_note_no},
                    {"name": "original_invoice_no", "value": order.invoice_no},
                    {"name": "reason_code", "value": reason_code},
                    {"name": "staff_id", "value": staff_id},
                ],
                "refund_line_items": self._refund_lines_payload(plan),
                "transactions": [{
                    "kind": "refund",
                    "gateway": GATEWAYS.get(payment_method, "razorpay_terminal"),
                    "amount": plan.amount.to_decimal(),
                    "parent_id": order.sale_transaction_id,
                }],
            }
        }
        url = f"{self.base_url}/orders/{order.order_id}/refunds.json"
        try:
            res = self.client.post(url, payload)
        except AmbiguousWriteError:
            # Did it land? Look for our credit note on the order before giving up.
            for rf in self.get_order(order.order_id).refunds:
                if rf.credit_note_no == credit_note_no:
                    return rf
            raise
        rf = res.get("refund", {})
        return RefundRecord(
            refund_id=rf.get("id"),
            created_at=rf.get("created_at", ""),
            amount=plan.amount,
            tax=plan.tax,
            credit_note_no=credit_note_no,
            line_ids=[l.line_id for l in plan.lines],
        )
