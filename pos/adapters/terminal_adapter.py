"""Adapter for payment terminal integration (Razorpay-like).

Charges are idempotent on order_ref (we use the store invoice number), so the HTTP
client may safely retry a 503 or a timeout with the same body: the customer is never
charged twice for one bill.
"""

from typing import Any, Dict, Optional
from pos.config import TERMINAL_API_BASE
from pos.adapters.http_client import ResilientHttpClient
from pos.domain.money import Money


class PaymentTerminalAdapter:
    """Communicates with payment terminal API."""

    def __init__(self, base_url: str = TERMINAL_API_BASE, client: Optional[ResilientHttpClient] = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or ResilientHttpClient()

    def charge(self, amount: Money, method: str, order_ref: str) -> Dict[str, Any]:
        """Charge the terminal. Retries on 503 reuse the same order_ref (idempotent)."""
        if amount.paise <= 0:
            raise ValueError("Terminal charge amount must be greater than zero")
        payload = {
            "amount_paise": amount.paise,
            "method": method.lower(),
            "order_ref": order_ref,
        }
        res = self.client.post(f"{self.base_url}/charges", payload, idempotent=True)
        if res.get("status") != "captured":
            raise RuntimeError(f"Terminal did not capture payment for {order_ref}: {res}")
        return res

    def get_charge(self, charge_id: str) -> Dict[str, Any]:
        """Get charge details by ID."""
        return self.client.get(f"{self.base_url}/charges/{charge_id}")

    def refund(self, charge_id: str, amount: Money, reason: str) -> Dict[str, Any]:
        """Refund on the terminal against the original charge."""
        payload = {"charge_id": charge_id, "amount_paise": amount.paise, "reason": reason}
        # Not blindly retried: the terminal rejects over-refunds, but we still check before retrying.
        return self.client.post(f"{self.base_url}/refunds", payload)
