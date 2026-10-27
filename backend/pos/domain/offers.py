"""Data-driven promotional offers engine.

Evaluates promotions defined in offers.json based on cart contents, customer tags,
lens types, date ranges, and stackability rules. Changing an offer is a data change.

Semantics (documented in README):
- An offer is eligible when it is active, inside its date window, its conditions hold,
  and (for the manager discount) an authorised approver and a reason code are supplied.
- `stackable: true` offers combine with each other. They are applied in `priority`
  order (lower number first); each line's discount is capped at what is left on the line.
- `stackable: false` offers cannot combine with any other offer.
- The engine compares "all eligible stackable offers together" against "each
  non-stackable offer on its own" and picks the outcome with the largest customer
  saving (ties go to the lower priority number). Staff never pick combinations by hand.
- Every offer gets an evaluation row: applied or not, amount, and why.
"""

import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from pos.config import OFFERS_FILE
from pos.domain.money import Money
from pos.domain.models import (
    AppliedOffer,
    Cart,
    CartItem,
    DiscountAllocation,
    ManualDiscount,
    StaffMember,
)


class OfferRule:
    def __init__(self, data: Dict[str, Any]):
        self.offer_id: str = data["offer_id"]
        self.name: str = data["name"]
        self.active: bool = data.get("active", True)
        self.valid_from: str = data["valid_from"]
        self.valid_to: str = data["valid_to"]
        self.stackable: bool = data.get("stackable", False)
        self.priority: int = data.get("priority", 50)
        self.rule: Dict[str, Any] = data.get("rule", {})

    @property
    def is_manual(self) -> bool:
        """Offers that need a staff role / reason code are manual (manager) discounts."""
        return bool(self.rule.get("requires"))

    def is_active_on(self, target_date: Optional[str] = None) -> bool:
        if not self.active:
            return False
        d = target_date or date.today().isoformat()
        return self.valid_from <= d <= self.valid_to


class OfferEvaluationResult:
    def __init__(
        self,
        applied_offers: List[AppliedOffer],
        total_discount: Money,
        line_discounts: Dict[int, Money],  # item index -> discount
        allocations: Dict[int, List[DiscountAllocation]],  # item index -> allocations
        evaluations: List[Dict[str, Any]],  # [{offer_id, applied, amount, why}]
    ):
        self.applied_offers = applied_offers
        self.total_discount = total_discount
        self.line_discounts = line_discounts
        self.allocations = allocations
        self.evaluations = evaluations


class OfferEngine:
    """Evaluates offers from offers.json against a Cart."""

    def __init__(self, offers_file: Optional[Path] = None):
        self.path = offers_file or OFFERS_FILE
        self.offers: List[OfferRule] = []
        self._load_offers()

    def _load_offers(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.offers = [OfferRule(item) for item in data]

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    @staticmethod
    def _lens_matches(item: CartItem, cond: Dict[str, Any]) -> bool:
        if item.variant.line_type != "lens":
            return False
        if "lens_type" in cond and item.variant.lens_type != cond["lens_type"]:
            return False
        if "index_min" in cond and (item.variant.index or 0) < cond["index_min"]:
            return False
        if "coating" in cond and item.variant.coating != cond["coating"]:
            return False
        return True

    @staticmethod
    def _complete_pairs(cart: Cart) -> List[str]:
        return [
            ref for ref, items in cart.pairs.items()
            if {"frame", "lens"} <= {i.variant.line_type for i in items}
        ]

    def check_eligibility(
        self,
        offer: OfferRule,
        cart: Cart,
        order_date: str,
        manual: Optional[ManualDiscount] = None,
        approver: Optional[StaffMember] = None,
    ) -> Tuple[bool, str]:
        """Return (eligible, why)."""
        if not offer.active:
            return False, "offer is switched off"
        if not offer.is_active_on(order_date):
            return False, f"outside validity {offer.valid_from}..{offer.valid_to}"

        r = offer.rule
        applies_to = r.get("applies_to")
        cond = r.get("condition", {})
        req = r.get("requires", {})
        customer = cart.customer

        if req:
            if manual is None:
                return False, "manual discount not requested"
            if req.get("role") and (approver is None or approver.role != req["role"]):
                return False, f"approver must be a {req['role']}"
            if approver is not None and not approver.can_override_discount:
                return False, f"approver {approver.staff_id} is not allowed to override discounts"
            if req.get("reason_code") and not manual.reason_code:
                return False, "reason code required"

        if "customer_tag" in cond and (not customer or not customer.has_tag(cond["customer_tag"])):
            return False, f"customer is not tagged '{cond['customer_tag']}'"
        if "min_pairs_in_cart" in cond and len(cart.pairs) < cond["min_pairs_in_cart"]:
            return False, f"needs {cond['min_pairs_in_cart']} pairs in cart, has {len(cart.pairs)}"

        if applies_to == "frame":
            if not any(i.variant.line_type == "frame" for i in cart.items):
                return False, "no frame in cart"
        elif applies_to == "lens":
            if not any(self._lens_matches(i, cond) for i in cart.items):
                return False, "no lens in cart matches the offer conditions"
        elif applies_to == "pair":
            if cond.get("has_frame_and_lens") and not self._complete_pairs(cart):
                return False, "no frame + lens pair in cart"
        elif applies_to == "cart":
            if not cart.items:
                return False, "cart is empty"
        else:
            return False, f"unsupported applies_to '{applies_to}' (data error)"

        return True, "conditions met"

    # ------------------------------------------------------------------
    # Discount amounts (uncapped, on MRP)
    # ------------------------------------------------------------------
    def _raw_line_discounts(
        self,
        offer: OfferRule,
        cart: Cart,
        remaining: List[Money],
        manual: Optional[ManualDiscount] = None,
    ) -> Dict[int, Money]:
        r = offer.rule
        applies_to = r.get("applies_to")
        cond = r.get("condition", {})
        disc = r.get("discount", {})
        dtype = disc.get("type")
        # The cap may sit on the rule or inside the discount block; accept both.
        cap_p = disc.get("max_discount_paise", r.get("max_discount_paise"))

        def amount_for(item: CartItem) -> Money:
            if dtype == "percent":
                bps = disc.get("value_bps", 0)
                if offer.is_manual and manual is not None:
                    bps = min(manual.bps, disc.get("value_bps_max", manual.bps))
                return item.line_subtotal.percent_bps(int(bps))
            if dtype == "flat":
                return Money(int(disc.get("value_paise", 0))) * item.quantity
            return Money.zero()

        out: Dict[int, Money] = {}
        if applies_to == "frame":
            for idx, item in enumerate(cart.items):
                if item.variant.line_type == "frame":
                    out[idx] = amount_for(item)
        elif applies_to == "lens":
            matching = [(idx, it) for idx, it in enumerate(cart.items) if self._lens_matches(it, cond)]
            if disc.get("on") == "lowest_priced_lens_line" and matching:
                matching = [min(matching, key=lambda p: (p[1].price.paise, p[0]))]
            for idx, item in matching:
                out[idx] = amount_for(item)
        elif applies_to == "pair":
            flat = Money(int(disc.get("value_paise", 0)))
            for ref in self._complete_pairs(cart):
                # Allocate the pair discount to the pair's lens line
                for idx, it in enumerate(cart.items):
                    if it.pair_ref == ref and it.variant.line_type == "lens":
                        out[idx] = out.get(idx, Money.zero()) + flat
                        break
        elif applies_to == "cart":
            if dtype == "flat":
                total = Money(int(disc.get("value_paise", 0)))
                weights = [m.paise for m in remaining]
                total = min(total, Money(sum(weights)))
                for idx, part in enumerate(total.allocate(weights)):
                    if part.paise:
                        out[idx] = part
            else:
                for idx, item in enumerate(cart.items):
                    out[idx] = amount_for(item)

        if cap_p is not None:
            # Cap the offer's total; trim from the largest lines first
            cap = Money(int(cap_p))
            excess = sum((m for m in out.values()), Money.zero()) - cap
            for idx in sorted(out, key=lambda i: -out[i].paise):
                if excess.paise <= 0:
                    break
                cut = min(excess, out[idx])
                out[idx] = out[idx] - cut
                excess = excess - cut
        return out

    def _apply_sequence(
        self,
        offers: List[OfferRule],
        cart: Cart,
        manual: Optional[ManualDiscount] = None,
    ) -> Tuple[Money, Dict[int, Money], List[Tuple[OfferRule, Dict[int, Money]]]]:
        """Apply offers in order, capping each line at what is still left to discount."""
        remaining = [item.line_subtotal for item in cart.items]
        per_offer: List[Tuple[OfferRule, Dict[int, Money]]] = []
        for off in offers:
            raw = self._raw_line_discounts(off, cart, remaining, manual)
            capped: Dict[int, Money] = {}
            for idx, amt in raw.items():
                take = min(amt, remaining[idx])
                if take.paise > 0:
                    capped[idx] = take
                    remaining[idx] = remaining[idx] - take
            per_offer.append((off, capped))
        line_totals: Dict[int, Money] = {}
        for _, lines in per_offer:
            for idx, amt in lines.items():
                line_totals[idx] = line_totals.get(idx, Money.zero()) + amt
        total = sum(line_totals.values(), Money.zero())
        return total, line_totals, per_offer

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def evaluate_best_offers(
        self,
        cart: Cart,
        order_date: Optional[str] = None,
        manual: Optional[ManualDiscount] = None,
        approver: Optional[StaffMember] = None,
    ) -> OfferEvaluationResult:
        """Evaluate and select the offer set with the largest customer saving."""
        d = order_date or date.today().isoformat()
        why: Dict[str, str] = {}
        eligible: List[OfferRule] = []
        for o in self.offers:
            ok, reason = self.check_eligibility(o, cart, d, manual, approver)
            why[o.offer_id] = reason
            if ok:
                eligible.append(o)

        stackable = sorted([o for o in eligible if o.stackable], key=lambda o: o.priority)
        candidates: List[Tuple[List[OfferRule], Money, Dict[int, Money], list, int]] = []
        if stackable:
            tot, lines, per = self._apply_sequence(stackable, cart, manual)
            candidates.append((stackable, tot, lines, per, stackable[0].priority))
        for off in (o for o in eligible if not o.stackable):
            tot, lines, per = self._apply_sequence([off], cart, manual)
            candidates.append(([off], tot, lines, per, off.priority))

        candidates = [c for c in candidates if c[1].paise > 0]
        if not candidates:
            evaluations = [
                {"offer_id": o.offer_id, "applied": False, "amount": Money.zero(), "why": why[o.offer_id]}
                for o in self.offers
            ]
            return OfferEvaluationResult([], Money.zero(), {}, {}, evaluations)

        candidates.sort(key=lambda c: (-c[1].paise, c[4]))
        best_offers, best_total, best_lines, best_per, _ = candidates[0]
        best_ids = {o.offer_id for o in best_offers}

        allocations: Dict[int, List[DiscountAllocation]] = {}
        applied: List[AppliedOffer] = []
        amounts: Dict[str, Money] = {}
        for off, lines in best_per:
            amt = sum(lines.values(), Money.zero())
            amounts[off.offer_id] = amt
            if amt.paise == 0:
                continue
            app_idx = len(applied)
            applied.append(AppliedOffer(offer_id=off.offer_id, name=off.name, amount=amt, index=app_idx))
            for idx, la in lines.items():
                allocations.setdefault(idx, []).append(
                    DiscountAllocation(amount=la, discount_application_index=app_idx, offer_id=off.offer_id)
                )

        evaluations = []
        for o in self.offers:
            if o.offer_id in best_ids and amounts.get(o.offer_id, Money.zero()).paise > 0:
                reason = "applied" if len(best_offers) == 1 else "applied (stacked)"
                evaluations.append({"offer_id": o.offer_id, "applied": True, "amount": amounts[o.offer_id], "why": reason})
            elif o in eligible:
                reason = (
                    "eligible but nothing left to discount on its lines" if o.offer_id in best_ids
                    else f"eligible but a better combination saves more ({best_total.format_inr()})"
                )
                evaluations.append({"offer_id": o.offer_id, "applied": False, "amount": Money.zero(), "why": reason})
            else:
                evaluations.append({"offer_id": o.offer_id, "applied": False, "amount": Money.zero(), "why": why[o.offer_id]})

        return OfferEvaluationResult(applied, best_total, best_lines, allocations, evaluations)

    def apply_offers_to_cart(
        self,
        cart: Cart,
        order_date: Optional[str] = None,
        manual: Optional[ManualDiscount] = None,
        approver: Optional[StaffMember] = None,
    ) -> OfferEvaluationResult:
        """Evaluate and mutate cart lines with discounts and allocations."""
        res = self.evaluate_best_offers(cart, order_date, manual, approver)
        for idx, item in enumerate(cart.items):
            item.discount = res.line_discounts.get(idx, Money.zero())
            item.discount_allocations = res.allocations.get(idx, [])
        return res
