"""Composition root: the only place that chooses concrete backends.

To replace Shopify (or the payment terminal, or the store tool), build the service here with a
different adapter that offers the same methods. Nothing in pos/domain or pos/services changes.
"""

from pos.adapters.shopify_adapter import ShopifyAdapter
from pos.adapters.smt_adapter import SmtAdapter
from pos.adapters.terminal_adapter import PaymentTerminalAdapter
from pos.services.pos_service import PosService


def build_service() -> PosService:
    return PosService(
        shopify_adapter=ShopifyAdapter(),
        smt_adapter=SmtAdapter(),
        terminal_adapter=PaymentTerminalAdapter(),
    )
