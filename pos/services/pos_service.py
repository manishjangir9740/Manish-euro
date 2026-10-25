"""POS service: orchestrates lookup, cart, offers, GST, payment, Shopify sync, refunds, day-end.

Order of operations at checkout (and why):
1. Validate everything that can be validated offline (Rx, stock, approver) - no side effects.
2. Price the cart: offers, then GST backed out per line.
3. Allocate the store invoice number (gapless). It is also the idempotency key for the
   terminal charge and for the Shopify order.
4. Charge the terminal (idempotent on the invoice number). If the charge fails, the
   invoice number is kept in the series as CANCELLED.
5. Write the order to the local outbox, then create it in Shopify. If Shopify is
   unreachable the bill is NOT lost: it stays pending and `sync-pending` replays it
   without creating a duplicate.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from pos.domain.audit import AuditLogger
from pos.domain.errors import AmbiguousWriteError
from pos.domain.invoice_series import CANCELLED, InvoiceSeriesManager
from pos.domain.models import (
    CHANNELS,
    PAYMENT_METHODS,
    Cart,
    CartItem,
    Customer,
    ManualDiscount,
    OrderRecord,
    Prescription,
    StaffMember,
)
from pos.domain.money import Money
from pos.domain.offers import OfferEngine, OfferEvaluationResult
from pos.domain.refunds import RefundPlan, plan_refund
from pos.domain.rx_validator import PrescriptionValidator, RxValidationError
from pos.domain.tax import TaxCalculator
from pos.domain.till import TillSessionManager
from pos.services.invoice_formatter import InvoiceFormatter
from pos.services.outbox import BillOutbox

MANAGER_MAX_BPS = 1000  # 10%, per Meena; the offers.json rule also carries value_bps_max
REASON_CODES = ("WALKOUT_RISK", "PRICE_MATCH", "DAMAGED_DISPLAY", "LOYALTY", "OTHER")
REFUND_REASONS = ("CHANGED_MIND", "WRONG_RX", "DEFECT", "DUPLICATE_BILL", "OTHER")


class PosService:
    """Core application service for Eluno Point of Sale."""

    def __init__(
        self,
        shopify_adapter: Any,   # order/customer/catalog backend (see pos.bootstrap)
        smt_adapter: Any,       # prescriptions + staff
        terminal_adapter: Any,  # payment terminal
        tax_calculator: Optional[TaxCalculator] = None,
        offer_engine: Optional[OfferEngine] = None,
        invoice_manager: Optional[InvoiceSeriesManager] = None,
        till_manager: Optional[TillSessionManager] = None,
        audit_logger: Optional[AuditLogger] = None,
        outbox: Optional[BillOutbox] = None,
    ):
        self.shopify = shopify_adapter
        self.smt = smt_adapter
        self.terminal = terminal_adapter
        self.tax_calc = tax_calculator or TaxCalculator()
        self.offers = offer_engine or OfferEngine()
        self.invoices = invoice_manager or InvoiceSeriesManager()
        self.till = till_manager or TillSessionManager()
        self.audit = audit_logger or AuditLogger()
        self.outbox = outbox or BillOutbox()

    # ------------------------------------------------------------------
    # 1. Customer & prescription lookup
    # ------------------------------------------------------------------
    def lookup_customer_and_rx(self, phone: str, target_date: Optional[str] = None):
        """Customer (Shopify) and latest VALID prescription (store tool). Either may be None."""
        customer = self.shopify.search_customer_by_phone(phone)
        rx = self.smt.get_latest_valid_prescription(phone, target_date)
        return customer, rx

    # ------------------------------------------------------------------
    # 2. Cart with clinical validation
    # ------------------------------------------------------------------
    def create_cart(self, customer: Customer, channel: str = "walk_in", staff_id: Optional[str] = None) -> Cart:
        if channel not in CHANNELS:
            raise ValueError(f"Unknown channel '{channel}'. Use one of {', '.join(CHANNELS)}.")
        return Cart(customer=customer, channel=channel, staff_id=staff_id)

    def add_pair_to_cart(
        self,
        cart: Cart,
        frame_variant_id: Optional[int],
        lens_variant_id: Optional[int],
        store_code: str,
        pair_ref: str = "1",
        rx: Optional[Prescription] = None,
        lens_config: Optional[str] = None,
        order_date: Optional[str] = None,
    ) -> List[CartItem]:
        """Validate stock and prescription, then add the frame and/or lens (a pair) to the cart."""
        location = self.shopify.get_location_by_code(store_code)
        new_items: List[CartItem] = []

        if frame_variant_id:
            frame = self.shopify.get_variant(frame_variant_id)
            if frame.line_type != "frame":
                raise ValueError(f"{frame.sku} is not a frame")
            if not frame.active:
                raise ValueError(f"Frame {frame.sku} is archived and cannot be sold.")
            if frame.inventory_item_id:
                already = sum(1 for i in cart.items if i.variant.id == frame.id)
                if self.shopify.check_stock(frame.inventory_item_id, location.id) - already <= 0:
                    raise ValueError(f"Frame {frame.sku} is out of stock at {store_code}. Check another store or reorder.")
            new_items.append(CartItem(variant=frame, quantity=1, pair_ref=pair_ref))

        if lens_variant_id:
            lens = self.shopify.get_variant(lens_variant_id)
            if lens.line_type != "lens":
                raise ValueError(f"{lens.sku} is not a lens")
            customer_id = cart.customer.id if cart.customer else None
            result = PrescriptionValidator.validate_lens_choice(lens, rx, order_date, customer_id)
            if not result.is_valid:
                raise RxValidationError(
                    f"Lens {lens.sku} blocked: " + " | ".join(result.errors), errors=result.errors
                )
            item = CartItem(
                variant=lens, quantity=1, pair_ref=pair_ref, rx=rx,
                lens_config=lens_config or f"{lens.lens_type}/{lens.index}/{lens.coating}",
            )
            item.warnings = result.warnings  # type: ignore[attr-defined]
            new_items.append(item)

        for it in new_items:
            cart.add_item(it)
        return new_items

    def suggest_lenses(self, rx: Prescription, lens_type: Optional[str] = None,
                       coating: Optional[str] = None, order_date: Optional[str] = None):
        """Lenses from the matrix that pass validation for this Rx, cheapest first."""
        return PrescriptionValidator.suitable_lenses(
            self.shopify.list_lens_variants(), rx, lens_type, coating, order_date
        )

    # ------------------------------------------------------------------
    # 3. Pricing: offers, then GST per line
    # ------------------------------------------------------------------
    def _resolve_manual_discount(
        self, store_code: str, manager_discount_bps: Optional[int], approver_id: Optional[str],
        reason_code: Optional[str],
    ):
        if not manager_discount_bps:
            return None, None
        if not approver_id or not reason_code:
            raise ValueError("A manager discount needs the approver's staff id and a reason code.")
        if not 0 < manager_discount_bps <= MANAGER_MAX_BPS:
            raise ValueError(f"Manager discount must be between 0.01% and {MANAGER_MAX_BPS / 100:.0f}%.")
        if reason_code not in REASON_CODES:
            raise ValueError(f"Unknown reason code '{reason_code}'. Use one of {', '.join(REASON_CODES)}.")
        approver = self.smt.get_staff_member(approver_id)
        if approver is None or approver.store_code.upper() != store_code.upper():
            raise ValueError(f"Approver {approver_id} is not staff at {store_code}.")
        if approver.role != "store_manager" or not approver.can_override_discount:
            raise ValueError(f"{approver_id} ({approver.role}) is not allowed to approve discounts.")
        return ManualDiscount(bps=manager_discount_bps, approver_id=approver_id, reason_code=reason_code), approver

    def prepare_cart_pricing(
        self, cart: Cart, order_date: Optional[str] = None,
        manual: Optional[ManualDiscount] = None, approver: Optional[StaffMember] = None,
    ) -> OfferEvaluationResult:
        eff = order_date or date.today().isoformat()
        res = self.offers.apply_offers_to_cart(cart, eff, manual, approver)
        for item in cart.items:
            self.tax_calc.apply_tax_to_line(item, order_date=eff)
        return res

    # ------------------------------------------------------------------
    # 4. Checkout
    # ------------------------------------------------------------------
    def checkout(
        self,
        cart: Cart,
        store_code: str,
        staff_id: str,
        payment_method: str = "upi",
        channel: Optional[str] = None,
        order_date: Optional[str] = None,
        till_session_id: Optional[str] = None,
        manager_discount_bps: Optional[int] = None,
        approver_id: Optional[str] = None,
        reason_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not cart.customer:
            raise ValueError("Customer required for checkout")
        if not cart.items:
            raise ValueError("Cart cannot be empty")
        payment_method = payment_method.lower()
        if payment_method not in PAYMENT_METHODS:
            raise ValueError(f"Unknown payment method '{payment_method}'.")
        channel = channel or cart.channel
        if channel not in CHANNELS:
            raise ValueError(f"Unknown channel '{channel}'.")

        location = self.shopify.get_location_by_code(store_code)
        eff_date = order_date or date.today().isoformat()

        # Re-validate lens/Rx at the moment of billing (Rx may have expired since the cart was built)
        for item in cart.items:
            if item.variant.line_type == "lens":
                r = PrescriptionValidator.validate_lens_choice(item.variant, item.rx, eff_date, cart.customer.id)
                if not r.is_valid:
                    raise RxValidationError("Billing blocked: " + " | ".join(r.errors), errors=r.errors)

        manual, approver = self._resolve_manual_discount(store_code, manager_discount_bps, approver_id, reason_code)
        offer_res = self.prepare_cart_pricing(cart, eff_date, manual, approver)
        total = cart.total_price
        applied_ids = [a.offer_id for a in offer_res.applied_offers]

        # Gapless store invoice number: also the idempotency key from here on
        self._start_series_if_new(store_code, location)
        invoice_no = self.invoices.next_invoice_number(store_code, location.invoice_prefix, eff_date)

        # Payment
        charge_id = f"cash_{invoice_no.replace('/', '_')}"
        if payment_method != "cash" and total.paise > 0:
            try:
                charge = self.terminal.charge(total, payment_method, order_ref=invoice_no)
                charge_id = charge["charge_id"]
            except Exception as exc:
                self.invoices.record_cancelled(store_code, invoice_no, f"payment failed: {exc}")
                self.audit.log(who=staff_id, what="INVOICE_CANCELLED_PAYMENT_FAILED", ref=invoice_no,
                               details={"error": str(exc), "amount_paise": total.paise})
                raise

        payload = self.shopify.build_order_payload(
            cart, location, invoice_no, channel, staff_id, payment_method, charge_id,
            offer_res.applied_offers, manual,
        )
        self.outbox.record(invoice_no, {
            "payload": payload, "location_id": location.id, "store_code": store_code,
            "charge_id": charge_id, "payment_method": payment_method, "amount_paise": total.paise,
            "till_session_id": till_session_id, "staff_id": staff_id,
        })

        order: Optional[OrderRecord] = None
        sync_error: Optional[str] = None
        try:
            order = self.shopify.submit_order(payload, invoice_no, location.id)
            self._after_sync(invoice_no, store_code, order, payment_method, till_session_id, total, staff_id)
        except AmbiguousWriteError as exc:
            sync_error = str(exc)
            self.outbox.mark_attempt_failed(invoice_no, sync_error)
        except Exception as exc:
            self.outbox.mark_attempt_failed(invoice_no, str(exc))
            self.audit.log(who=staff_id, what="ORDER_CREATION_FAILED_POST_CHARGE", ref=invoice_no,
                           details={"error": str(exc), "charge_id": charge_id, "amount_paise": total.paise})
            raise

        if order is None:
            self.audit.log(who=staff_id, what="ORDER_PENDING_SYNC", ref=invoice_no,
                           details={"error": sync_error, "charge_id": charge_id, "amount_paise": total.paise})

        self.audit.log(
            who=staff_id, what="ORDER_COMPLETED" if order else "ORDER_PAID_PENDING_SYNC", ref=invoice_no,
            reason_code=manual.reason_code if manual else None,
            details={
                "shopify_order_id": order.order_id if order else None,
                "total_paise": total.paise, "discounts_paise": cart.total_discounts.paise,
                "offers": applied_ids, "channel": channel, "payment_method": payment_method,
                "discount_approver_id": manual.approver_id if manual else None,
            },
        )

        invoice_text = InvoiceFormatter.format_invoice(
            invoice_no=invoice_no, date_str=eff_date, store=location, customer=cart.customer, cart=cart,
            staff_id=staff_id, channel=channel, payment_method=payment_method, terminal_ref=charge_id,
            shopify_order_num=order.order_number if order else None,
            shopify_order_id=order.order_id if order else None,
            applied_offers=applied_ids,
            rx_id=next((i.rx.rx_id for i in cart.items if i.rx), None),
        )
        warnings = [w for i in cart.items for w in getattr(i, "warnings", [])]
        return {
            "invoice_no": invoice_no,
            "status": "synced" if order else "pending_sync",
            "order_id": order.order_id if order else None,
            "order_number": order.order_number if order else None,
            "charge_id": charge_id,
            "total_price": total,
            "total_tax": cart.total_tax,
            "offer_evaluations": offer_res.evaluations,
            "warnings": warnings,
            "invoice_text": invoice_text,
            "order": order,
        }

    def _start_series_if_new(self, store_code: str, location) -> None:
        """A store's local series must continue after the invoices already in Shopify (no collisions)."""
        if not self.invoices.has_store(store_code):
            last_inv, last_cn = self.shopify.last_document_numbers(location.id, location.invoice_prefix)
            self.invoices.start_after(store_code, location.invoice_prefix, last_inv, last_cn)

    def _after_sync(self, invoice_no, store_code, order, payment_method, till_session_id, total, staff_id):
        self.invoices.mark_synced(store_code, invoice_no)
        self.outbox.mark_synced(invoice_no, order.order_id)
        if payment_method == "cash" and total.paise > 0:
            if not till_session_id:
                self.audit.log(who=staff_id, what="CASH_SALE_WITHOUT_TILL_SESSION", ref=invoice_no,
                               details={"amount_paise": total.paise})
                return
            try:
                self.till.record_cash_movement(till_session_id, "cash_sale", total, ref=invoice_no, staff_id=staff_id)
            except Exception as exc:  # never swallow silently: finance must see it
                self.audit.log(who=staff_id, what="TILL_RECORD_FAILED", ref=invoice_no,
                               details={"error": str(exc), "amount_paise": total.paise})

    def sync_pending(self) -> List[Dict[str, Any]]:
        """Replay bills that were charged but not yet saved in Shopify. Never creates duplicates."""
        results = []
        for entry in self.outbox.pending():
            inv = entry["invoice_no"]
            try:
                order = self.shopify.submit_order(
                    entry["payload"], inv, entry["location_id"], check_existing_first=True
                )
                self._after_sync(inv, entry["store_code"], order, entry["payment_method"],
                                 entry.get("till_session_id"), Money(entry["amount_paise"]), entry["staff_id"])
                self.audit.log(who=entry["staff_id"], what="PENDING_BILL_SYNCED", ref=inv,
                               details={"shopify_order_id": order.order_id})
                results.append({"invoice_no": inv, "status": "synced", "order_id": order.order_id})
            except Exception as exc:
                self.outbox.mark_attempt_failed(inv, str(exc))
                results.append({"invoice_no": inv, "status": "pending", "error": str(exc)})
        return results

    # ------------------------------------------------------------------
    # 5. Refunds (full by default, partial by line)
    # ------------------------------------------------------------------
    def process_refund(
        self,
        order_id: int,
        staff_id: str,
        reason: str = "CHANGED_MIND",
        line_item_ids_to_refund: Optional[List[int]] = None,
        till_session_id: Optional[str] = None,
        refund_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        if reason not in REFUND_REASONS:
            raise ValueError(f"Unknown refund reason '{reason}'. Use one of {', '.join(REFUND_REASONS)}.")
        order = self.shopify.get_order(order_id)
        if not order.invoice_no or not order.store_code:
            raise ValueError(f"Order {order.name} was not billed through the Eluno POS (no invoice number).")

        plan: RefundPlan = plan_refund(order, line_item_ids_to_refund)
        calc_amount, _ = self.shopify.calculate_refund(plan)
        if calc_amount != plan.amount:
            raise ValueError(
                f"Refund mismatch: POS computes {plan.amount.format_inr()} but Shopify computes "
                f"{calc_amount.format_inr()}. Nothing was refunded; escalate to Finance."
            )

        self._start_series_if_new(order.store_code, self.shopify.get_location_by_code(order.store_code))
        credit_note_no = self.invoices.next_credit_note_number(order.store_code, order.invoice_no, refund_date)
        method = order.payment_method
        try:
            if method != "cash" and order.sale_authorization and not order.sale_authorization.startswith("cash_"):
                self.terminal.refund(order.sale_authorization, plan.amount, reason)
            record = self.shopify.create_refund(plan, credit_note_no, reason, staff_id, method)
        except Exception as exc:
            self.invoices.mark_credit_note(order.store_code, credit_note_no, CANCELLED)
            self.audit.log(who=staff_id, what="REFUND_FAILED", ref=credit_note_no, reason_code=reason,
                           details={"error": str(exc), "order_id": order_id, "amount_paise": plan.amount.paise})
            raise
        self.invoices.mark_credit_note(order.store_code, credit_note_no, "synced")

        if method == "cash":
            if till_session_id:
                try:
                    self.till.record_cash_movement(till_session_id, "cash_refund", plan.amount,
                                                   ref=credit_note_no, reason=reason, staff_id=staff_id)
                except Exception as exc:
                    self.audit.log(who=staff_id, what="TILL_RECORD_FAILED", ref=credit_note_no,
                                   details={"error": str(exc)})
            else:
                self.audit.log(who=staff_id, what="CASH_REFUND_WITHOUT_TILL_SESSION", ref=credit_note_no,
                               details={"amount_paise": plan.amount.paise})

        self.audit.log(who=staff_id, what="REFUND_COMPLETED", ref=credit_note_no, reason_code=reason, details={
            "order_id": order_id, "original_invoice": order.invoice_no, "amount_paise": plan.amount.paise,
            "tax_reversed_paise": plan.tax.paise, "full": plan.is_full,
            "lines": [{"line_id": l.line_id, "restocked": l.restock} for l in plan.lines],
        })
        return {
            "refund_id": record.refund_id,
            "credit_note_no": credit_note_no,
            "original_invoice_no": order.invoice_no,
            "refund_amount": plan.amount,
            "taxable_reversed": plan.taxable,
            "tax_reversed": plan.tax,
            "restocked_at": order.location_id if any(l.restock for l in plan.lines) else None,
            "is_full": plan.is_full,
            "plan": plan,
        }

    # ------------------------------------------------------------------
    # 6. Day-end report (source of truth: Shopify orders)
    # ------------------------------------------------------------------
    def generate_day_end_report(self, store_code: str, date_str: str) -> Dict[str, Any]:
        location = self.shopify.get_location_by_code(store_code)
        orders = self.shopify.orders_for_location(
            location.id, f"{date_str}T00:00:00+05:30", f"{date_str}T23:59:59+05:30"
        )
        orders = [o for o in orders if not o.cancelled]

        gross = discounts = tax = taxable = refunds = refund_tax = Money.zero()
        pay_sales: Dict[str, Money] = {}
        pay_refunds: Dict[str, Money] = {}
        channels: Dict[str, Dict[str, Any]] = {}
        for o in orders:
            gross += o.subtotal
            discounts += o.discounts
            tax += o.tax
            taxable += o.total - o.tax
            pay_sales[o.payment_method] = pay_sales.get(o.payment_method, Money.zero()) + o.total
            ch = channels.setdefault(o.channel, {"bills": 0, "total": Money.zero()})
            ch["bills"] += 1
            ch["total"] += o.total
            for rf in o.refunds:
                refunds += rf.amount
                refund_tax += rf.tax
                pay_refunds[o.payment_method] = pay_refunds.get(o.payment_method, Money.zero()) + rf.amount

        net_by_method = {
            m: pay_sales.get(m, Money.zero()) - pay_refunds.get(m, Money.zero())
            for m in sorted(set(pay_sales) | set(pay_refunds))
        }
        bill_count = len(orders)
        total_billed = gross - discounts
        avg = Money(total_billed.paise // bill_count) if bill_count else Money.zero()

        mismatches = self._reconcile(store_code, date_str, orders, pay_sales.get("cash", Money.zero()), pay_refunds.get("cash", Money.zero()))

        lines = [
            "=" * 64,
            f"ELUNO DAY-END REPORT - {location.name.upper()}",
            f"Date: {date_str}   Store: {store_code}   Source: Shopify orders",
            "=" * 64,
            f"Bills                : {bill_count}",
            f"Gross (MRP)          : {gross.format_inr()}",
            f"Discounts            : {discounts.format_inr()}",
            f"Net billed           : {total_billed.format_inr()}",
            f"  Taxable value      : {taxable.format_inr()}",
            f"  GST (CGST+SGST)    : {tax.format_inr()}",
            f"Refunds              : {refunds.format_inr()}  (tax reversed {refund_tax.format_inr()})",
            f"Net after refunds    : {(total_billed - refunds).format_inr()}",
            f"Average bill         : {avg.format_inr()}",
            "-" * 64,
            "BY PAYMENT METHOD (billed / refunded / net):",
        ]
        for m in net_by_method:
            lines.append(f"  {m.upper():<8} {pay_sales.get(m, Money.zero()).format_inr():>14} "
                         f"{pay_refunds.get(m, Money.zero()).format_inr():>14} {net_by_method[m].format_inr():>14}")
        lines += ["-" * 64, "BY CHANNEL:"]
        for ch in sorted(channels):
            lines.append(f"  {ch:<16} {channels[ch]['bills']:>3} bills  {channels[ch]['total'].format_inr():>14}")
        lines += ["-" * 64, "RECONCILIATION:"]
        lines += [f"  MISMATCH: {m}" for m in mismatches] or ["  OK: invoice register and till agree with Shopify"]
        lines.append("=" * 64)

        return {
            "store_code": store_code, "date": date_str, "bill_count": bill_count,
            "gross_sales": gross, "total_discounts": discounts, "total_taxable": taxable, "total_tax": tax,
            "net_billed": total_billed, "total_refunds": refunds, "refund_tax": refund_tax,
            "average_bill": avg, "payment_splits": pay_sales, "payment_refunds": pay_refunds,
            "payment_net": net_by_method,
            "channel_splits": {c: v["bills"] for c, v in channels.items()},
            "channel_totals": {c: v["total"] for c, v in channels.items()},
            "mismatches": mismatches, "report_text": "\n".join(lines),
        }

    def _reconcile(self, store_code, date_str, orders, cash_sales, cash_refunds) -> List[str]:
        """Compare Shopify with what the till knows locally. Differences are shown, never hidden."""
        problems: List[str] = []
        shopify_invoices = {o.invoice_no for o in orders if o.invoice_no}
        for rec in self.invoices.invoices_for(store_code, date_str):
            if rec["status"] == "issued" and rec["invoice_no"] not in shopify_invoices:
                problems.append(f"{rec['invoice_no']} is paid but not in Shopify yet (run sync-pending)")
        session = self.till.find_session(store_code, date_str)
        if session:
            till_sales = sum(m["amount_paise"] for m in session["movements"] if m["type"] == "cash_sale")
            if till_sales != cash_sales.paise:
                problems.append(f"cash sales: till {Money(till_sales).format_inr()} vs Shopify {cash_sales.format_inr()}")
            till_refunds = -sum(m["amount_paise"] for m in session["movements"] if m["type"] == "cash_refund")
            if till_refunds != cash_refunds.paise:
                problems.append(f"cash refunds: till {Money(till_refunds).format_inr()} vs Shopify {cash_refunds.format_inr()}")
            if session.get("variance_alert"):
                problems.append(f"till variance {Money(session['variance_paise']).format_inr()} exceeds the Rs 200 limit")
        return problems
