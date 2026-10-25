"""Refund planning: which lines, how much, tax reversed per line, and what is restocked.

Rules (Farhan / Vikram):
- Frames restock at the store that billed them (the order's location), never HQ.
- Lenses are made to order: scrapped, never restocked.
- Tax is reversed per refunded line: the credit note shows each line's taxable value and tax.
- The refund transaction is recorded against the original sale transaction.
"""

from dataclasses import dataclass
from typing import Iterable, List, Optional
from pos.domain.models import OrderRecord, RefundLine
from pos.domain.money import Money


class RefundError(ValueError):
    pass


@dataclass
class RefundPlan:
    order: OrderRecord
    lines: List[RefundLine]

    @property
    def amount(self) -> Money:
        return sum((l.gross for l in self.lines), Money.zero())

    @property
    def tax(self) -> Money:
        return sum((l.tax for l in self.lines), Money.zero())

    @property
    def taxable(self) -> Money:
        return self.amount - self.tax

    @property
    def is_full(self) -> bool:
        return {l.line_id for l in self.lines} | set(self.order.refunded_line_ids) == {
            l.line_id for l in self.order.lines
        }


def plan_refund(order: OrderRecord, line_ids: Optional[Iterable[int]] = None) -> RefundPlan:
    """Build a refund plan for the whole order (default) or the given line ids."""
    if order.cancelled:
        raise RefundError(f"Order {order.name} is cancelled; nothing to refund.")
    wanted = set(line_ids) if line_ids else None
    known = {l.line_id for l in order.lines}
    if wanted and not wanted <= known:
        raise RefundError(f"Line(s) {sorted(wanted - known)} are not on order {order.name}.")

    already = set(order.refunded_line_ids)
    if wanted and wanted & already:
        raise RefundError(f"Line(s) {sorted(wanted & already)} on {order.name} were already refunded.")

    lines: List[RefundLine] = []
    for li in order.lines:
        if wanted is not None and li.line_id not in wanted:
            continue
        if li.line_id in already:
            continue
        restock = li.line_type == "frame"
        lines.append(RefundLine(
            line_id=li.line_id,
            quantity=li.quantity,
            restock=restock,
            location_id=order.location_id if restock else None,
            gross=li.gross,
            tax=li.tax,
        ))

    if not lines:
        raise RefundError(f"Order {order.name} has nothing left to refund.")
    plan = RefundPlan(order=order, lines=lines)
    remaining = order.captured - order.refunded
    if plan.amount > remaining:
        raise RefundError(
            f"Refund {plan.amount.format_inr()} exceeds what is left to refund on {order.name} "
            f"({remaining.format_inr()})."
        )
    return plan
