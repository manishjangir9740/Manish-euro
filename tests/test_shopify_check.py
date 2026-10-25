"""Real-Shopify plumbing: token header, and the read-only compatibility check."""
import unittest
from unittest.mock import MagicMock, patch

from pos.adapters.http_client import HttpStatusError, ResilientHttpClient
from pos.adapters.shopify_adapter import ShopifyAdapter
from pos.shopify_check import run_checks


class TestAccessToken(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_default_headers_are_sent_on_every_request(self, urlopen):
        resp = MagicMock()
        resp.read.return_value = b"{}"
        resp.__enter__.return_value = resp
        urlopen.return_value = resp
        ResilientHttpClient(default_headers={"X-Shopify-Access-Token": "shpat_x"}).get("https://s/admin/x.json")
        sent = urlopen.call_args[0][0]
        self.assertEqual(sent.get_header("X-shopify-access-token"), "shpat_x")

    def test_check_is_read_only_and_reports_missing_eluno_data(self):
        client = MagicMock()
        # a real store: no `eluno` blocks anywhere
        client.get.side_effect = lambda url: (
            {"shop": {"name": "Demo", "currency": "INR", "taxes_included": True}} if "shop.json" in url else
            {"locations": [{"id": 1, "name": "Main"}]} if "locations" in url else
            {"products": [{"id": 1, "variants": [{"id": 2, "inventory_item_id": 3}]}]} if "products" in url else
            {"customers": []} if "customers" in url else
            {"orders": []} if "orders" in url else {"inventory_levels": []})
        res = {n: ok for n, ok, _ in run_checks(ShopifyAdapter(base_url="https://s/admin/api/v", client=client))}
        self.assertTrue(res["Connects and authenticates (shop.json)"])
        self.assertFalse(res["Each store location has an Eluno store_code (needed for invoice numbers)"])
        self.assertFalse(res["Variants carry an HSN code"])
        client.post.assert_not_called()  # read-only

    def test_bad_token_stops_after_the_first_check(self):
        client = MagicMock()
        client.get.side_effect = HttpStatusError("u", 401, {"errors": "Invalid API key or access token"})
        out = run_checks(ShopifyAdapter(base_url="https://s/admin/api/v", client=client))
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0][1])


if __name__ == "__main__":
    unittest.main()
