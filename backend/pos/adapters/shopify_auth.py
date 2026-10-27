"""Shopify Dev Dashboard apps: exchange a Client ID + secret for a short-lived Admin API token.

Uses the OAuth client-credentials grant. The token expires (about 24 hours), so it is fetched
when the service starts and never written to disk.
"""

import json
import urllib.error
import urllib.parse
import urllib.request


class ShopifyAuthError(Exception):
    pass


def fetch_client_credentials_token(shop: str, client_id: str, client_secret: str, timeout: float = 15.0) -> str:
    url = f"https://{shop}/admin/oauth/access_token"
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ShopifyAuthError(f"Shopify refused the client credentials (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise ShopifyAuthError(f"Could not reach {shop}: {exc.reason}") from exc
    token = data.get("access_token")
    if not token:
        raise ShopifyAuthError(f"No access_token in Shopify's reply: {list(data)}")
    return token
