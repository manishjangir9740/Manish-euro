"""Domain entities and value objects for Eluno POS.

Clean domain models completely independent of Shopify's internal data formats.
Adapters translate external payloads into these types and back.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Any
from pos.domain.money import Money

CHANNELS = ("walk_in", "whatsapp_booked", "online_pickup")
PAYMENT_METHODS = ("upi", "card", "cash")


@dataclass
class EyeRx:
    sph: float
    cyl: float
    axis: Optional[int] = None
    add: Optional[float] = None


@dataclass
class Prescription:
    rx_id: str
    customer_id: int
    phone: str
    date: str
    source: str  # 'in_store' or 'external'
    optometrist_id: Optional[str]
    od: EyeRx
    os: EyeRx
    pd: Dict[str, Any]
    valid_until: str
    notes: Optional[str] = None

    def is_valid_for_date(self, check_date: Optional[str] = None) -> bool:
        """Valid when the test date is not in the future and valid_until has not passed."""
        target = check_date or date.today().isoformat()
        return self.date <= target <= self.valid_until


@dataclass
class Customer:
    id: int
    first_name: str
    last_name: str
    phone: str
    tags: List[str]
    total_spent: Money

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_priority(self) -> bool:
        return "priority" in self.tags

    @property
    def campaigns(self) -> List[str]:
        return [t.split(":", 1)[1] for t in self.tags if t.startswith("campaign:")]

    @property
    def billing_flags(self) -> List[str]:
        """Flags shown on the billing screen, same as the queue tool (priority, campaign walk-ins)."""
        flags = ["PRIORITY"] if self.is_priority else []
        flags += [f"CAMPAIGN:{c}" for c in self.campaigns]
        return flags

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags


@dataclass
class LensLimits:
    sph_min: float
    sph_max: float
    cyl_abs_max: float
    add_required: bool
    add_min: Optional[float] = None
    add_max: Optional[float] = None


@dataclass
class Variant:
    id: int
    product_id: int
    sku: str
    title: str
    price: Money
    inventory_item_id: Optional[int]
    line_type: str  # 'frame' or 'lens'
    hsn: str
    category: Optional[str] = None
    lens_type: Optional[str] = None  # 'single_vision' | 'progressive' | 'bifocal'
    index: Optional[float] = None
    coating: Optional[str] = None
    rx_limits: Optional[LensLimits] = None
    lab_tat_days: Optional[int] = None
    rx_able: bool = True
    product_title: Optional[str] = None
    active: bool = True  # archived products appear in history but cannot be sold

    @property
    def display_name(self) -> str:
        if self.product_title:
            return f"{self.product_title} {self.title}"
        return self.title


@dataclass
class TaxLine:
    title: str  # 'CGST' or 'SGST'
    rate_bps: int  # e.g. 900 for 9%
    price: Money

    @property
    def rate(self) -> float:
        """Rate as a fraction (0.09) — Shopify's representation, used only at the boundary."""
        return self.rate_bps / 10000


@dataclass
class DiscountAllocation:
    amount: Money
    discount_application_index: int
    offer_id: str


@dataclass
class CartItem:
    variant: Variant
    quantity: int = 1
    pair_ref: str = "1"
    rx: Optional[Prescription] = None
    lens_config: Optional[str] = None  # e.g. "progressive/1.6/blue_cut"
    discount: Money = field(default_factory=Money.zero)
    discount_allocations: List[DiscountAllocation] = field(default_factory=list)
    tax_lines: List[TaxLine] = field(default_factory=list)
    taxable_amount: Money = field(default_factory=Money.zero)

    @property
    def price(self) -> Money:
        return self.variant.price

    @property
    def line_subtotal(self) -> Money:
        return self.price * self.quantity

    @property
    def gross_amount(self) -> Money:
        """MRP inclusive amount less line discount."""
        return self.line_subtotal - self.discount

    @property
    def total_tax(self) -> Money:
        return sum((t.price for t in self.tax_lines), Money.zero())


@dataclass
class Cart:
    items: List[CartItem] = field(default_factory=list)
    customer: Optional[Customer] = None
    channel: str = "walk_in"  # 'walk_in', 'whatsapp_booked', 'online_pickup'
    staff_id: Optional[str] = None

    def add_item(self, item: CartItem) -> None:
        self.items.append(item)

    @property
    def subtotal_price(self) -> Money:
        return sum((item.line_subtotal for item in self.items), Money.zero())

    @property
    def total_discounts(self) -> Money:
        return sum((item.discount for item in self.items), Money.zero())

    @property
    def total_tax(self) -> Money:
        return sum((item.total_tax for item in self.items), Money.zero())

    @property
    def total_taxable(self) -> Money:
        return sum((item.taxable_amount for item in self.items), Money.zero())

    @property
    def total_price(self) -> Money:
        return self.subtotal_price - self.total_discounts

    @property
    def pairs(self) -> Dict[str, List[CartItem]]:
        result: Dict[str, List[CartItem]] = {}
        for item in self.items:
            result.setdefault(item.pair_ref, []).append(item)
        return result


@dataclass
class AppliedOffer:
    """One discount application on a bill (an offer or the manager discount)."""
    offer_id: str
    name: str
    amount: Money
    index: int


@dataclass
class ManualDiscount:
    """Manager discount request. Finance requires a reason code and the approver's identity."""
    bps: int
    approver_id: str
    reason_code: str


@dataclass
class StoreLocation:
    id: int
    name: str
    store_code: str
    invoice_prefix: str
    state_code: str
    kind: str  # 'store' or 'warehouse'


@dataclass
class StaffMember:
    staff_id: str
    name: str
    role: str  # 'sales', 'optometrist', 'store_manager'
    store_code: str
    can_override_discount: bool = False
    progressive_expert: bool = False


# ---------------------------------------------------------------------------
# Recorded orders, as read back from the system of record (backend-agnostic)
# ---------------------------------------------------------------------------
@dataclass
class OrderLine:
    line_id: int
    sku: str
    line_type: str  # 'frame' | 'lens'
    quantity: int
    price: Money
    discount: Money
    tax: Money
    rx_id: Optional[str] = None

    @property
    def gross(self) -> Money:
        return self.price * self.quantity - self.discount

    @property
    def taxable(self) -> Money:
        return self.gross - self.tax


@dataclass
class RefundRecord:
    refund_id: int
    created_at: str
    amount: Money
    tax: Money
    credit_note_no: Optional[str]
    line_ids: List[int]


@dataclass
class OrderRecord:
    order_id: int
    order_number: int
    name: str
    created_at: str
    location_id: int
    customer_id: Optional[int]
    invoice_no: Optional[str]
    store_code: Optional[str]
    channel: str
    staff_id: Optional[str]
    payment_method: str
    subtotal: Money
    discounts: Money
    tax: Money
    total: Money
    lines: List[OrderLine]
    sale_transaction_id: Optional[int]
    sale_authorization: Optional[str]
    captured: Money
    refunds: List[RefundRecord]
    cancelled: bool = False
    parent_invoice_no: Optional[str] = None

    @property
    def refunded(self) -> Money:
        return sum((r.amount for r in self.refunds), Money.zero())

    @property
    def refunded_line_ids(self) -> List[int]:
        return [lid for r in self.refunds for lid in r.line_ids]


@dataclass
class RefundLine:
    """A line the POS wants refunded. Restock decision is made in the domain, not the adapter."""
    line_id: int
    quantity: int
    restock: bool
    location_id: Optional[int]
    gross: Money
    tax: Money
