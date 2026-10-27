"""Composition root: the only place that chooses concrete backends.

To replace Shopify (or the payment terminal, or the store tool), build the service here with a
different adapter that offers the same methods. Nothing in pos/domain or pos/services changes.
"""

from pos import config
from pos.adapters.http_client import ResilientHttpClient
from pos.adapters.shopify_adapter import ShopifyAdapter
from pos.adapters.shopify_auth import ShopifyAuthError, fetch_client_credentials_token
from pos.adapters.smt_adapter import SmtAdapter
from pos.adapters.terminal_adapter import PaymentTerminalAdapter
from pos.services.pos_service import PosService


def build_shopify() -> ShopifyAdapter:
    """Mock by default; the real Admin API when SHOPIFY_SHOP / SHOPIFY_ACCESS_TOKEN are set."""
    if config.SHOPIFY_SHOP:
        token = config.SHOPIFY_ACCESS_TOKEN
        if not token and config.SHOPIFY_CLIENT_ID and config.SHOPIFY_CLIENT_SECRET:
            try:
                token = fetch_client_credentials_token(
                    config.SHOPIFY_SHOP, config.SHOPIFY_CLIENT_ID, config.SHOPIFY_CLIENT_SECRET)
            except ShopifyAuthError as exc:
                raise SystemExit(str(exc))
        if not token:
            raise SystemExit("SHOPIFY_SHOP is set but there is no SHOPIFY_ACCESS_TOKEN "
                             "(or SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET).")
        client = ResilientHttpClient(default_headers={"X-Shopify-Access-Token": token})
        return ShopifyAdapter(client=client)
    return ShopifyAdapter()


def build_service() -> PosService:
    return PosService(
        shopify_adapter=build_shopify(),
        smt_adapter=SmtAdapter(),
        terminal_adapter=PaymentTerminalAdapter(),
    )
