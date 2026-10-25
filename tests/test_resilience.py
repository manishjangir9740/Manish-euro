"""429/503 handling, idempotency, and the paid-but-not-in-Shopify outbox."""
import io
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from pos.adapters.http_client import AmbiguousWriteError, HttpStatusError, ResilientHttpClient
from pos.adapters.shopify_adapter import ShopifyAdapter
from pos.adapters.terminal_adapter import PaymentTerminalAdapter
from pos.domain.money import Money
from tests.helpers import HSR, make_service, order_record, pair_cart, tmpdir


def http_error(code, headers=None):
    return urllib.error.HTTPError("http://mock", code, "err", headers or {}, io.BytesIO(b'{"errors": "x"}'))


def ok(body=b'{"success": true}'):
    r = MagicMock()
    r.read.return_value = body
    r.__enter__.return_value = r
    return r


@patch("time.sleep")
class TestHttpClient(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_429_honours_retry_after_and_retries_even_for_posts(self, urlopen, sleep):
        urlopen.side_effect = [http_error(429, {"Retry-After": "0.5"}), ok()]
        res = ResilientHttpClient(max_retries=3).post("http://mock/orders", {"a": 1})
        self.assertEqual(res, {"success": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_with(0.5)

    @patch("urllib.request.urlopen")
    def test_get_retries_503(self, urlopen, sleep):
        urlopen.side_effect = [http_error(503), ok()]
        self.assertEqual(ResilientHttpClient().get("http://mock/x"), {"success": True})

    @patch("urllib.request.urlopen")
    def test_non_idempotent_post_is_not_blindly_retried_on_503(self, urlopen, sleep):
        urlopen.side_effect = [http_error(503), ok()]
        with self.assertRaises(AmbiguousWriteError):
            ResilientHttpClient().post("http://mock/orders", {"a": 1})
        self.assertEqual(urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_non_idempotent_post_timeout_is_ambiguous(self, urlopen, sleep):
        urlopen.side_effect = TimeoutError("timed out")
        with self.assertRaises(AmbiguousWriteError):
            ResilientHttpClient().post("http://mock/orders", {"a": 1})
        self.assertEqual(urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_idempotent_post_retries_503(self, urlopen, sleep):
        urlopen.side_effect = [http_error(503), ok()]
        self.assertEqual(ResilientHttpClient().post("http://mock/c", {}, idempotent=True), {"success": True})

    @patch("urllib.request.urlopen")
    def test_4xx_is_not_retried(self, urlopen, sleep):
        urlopen.side_effect = [http_error(422)]
        with self.assertRaises(HttpStatusError):
            ResilientHttpClient().post("http://mock/orders", {})
        self.assertEqual(urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_gives_up_after_max_retries(self, urlopen, sleep):
        urlopen.side_effect = [http_error(429)] * 10
        with self.assertRaises(HttpStatusError):
            ResilientHttpClient(max_retries=2).get("http://mock/x")
        self.assertEqual(urlopen.call_count, 3)


@patch("time.sleep")
class TestTerminalIdempotency(unittest.TestCase):
    def test_503_retried_with_same_order_ref(self, sleep):
        client = MagicMock()
        client.post.return_value = {"charge_id": "chg_1", "status": "captured"}
        PaymentTerminalAdapter(client=client).charge(Money(1907215), "upi", "ELU/HSR/FY26/00001")
        _, kwargs = client.post.call_args
        self.assertTrue(kwargs["idempotent"])
        self.assertEqual(client.post.call_args[0][1]["order_ref"], "ELU/HSR/FY26/00001")

    def test_zero_charge_rejected(self, sleep):
        with self.assertRaises(ValueError):
            PaymentTerminalAdapter(client=MagicMock()).charge(Money(0), "upi", "x")


class TestNoDuplicateOrders(unittest.TestCase):
    def test_timeout_after_server_created_the_order_does_not_create_a_second(self):
        client = MagicMock()
        existing = order_record()
        raw = {"id": existing.order_id, "order_number": 1001, "location_id": 70000002,
               "note_attributes": [{"name": "invoice_no", "value": "ELU/HSR/FY26/00001"}],
               "line_items": [], "transactions": [], "refunds": []}
        client.post.side_effect = AmbiguousWriteError("u", TimeoutError())
        client.get.return_value = {"orders": [raw]}
        got = ShopifyAdapter(base_url="http://x", client=client).submit_order({"order": {}}, "ELU/HSR/FY26/00001", 70000002)
        self.assertEqual(got.order_id, existing.order_id)
        self.assertEqual(client.post.call_count, 1)

    def test_timeout_when_order_did_not_land_retries_the_create(self):
        client = MagicMock()
        raw = {"id": 5, "order_number": 1, "location_id": 1, "note_attributes": [], "line_items": [],
               "transactions": [], "refunds": []}
        client.post.side_effect = [AmbiguousWriteError("u", TimeoutError()), {"order": raw}]
        client.get.return_value = {"orders": []}
        got = ShopifyAdapter(base_url="http://x", client=client).submit_order({"order": {}}, "INV", 1)
        self.assertEqual(got.order_id, 5)
        self.assertEqual(client.post.call_count, 2)


class TestCheckoutResilience(unittest.TestCase):
    def setUp(self):
        self._d, self.tmp = tmpdir()
        self.addCleanup(self._d.cleanup)
        self.shopify, self.terminal = MagicMock(), MagicMock()
        self.shopify.build_order_payload.return_value = {"order": {"note_attributes": []}}
        self.terminal.charge.return_value = {"charge_id": "chg_9", "status": "captured"}
        self.svc = make_service(self.tmp, self.shopify, self.terminal)

    def _checkout(self, **kw):
        return self.svc.checkout(pair_cart(), "HSR", "S105", "upi", order_date="2026-10-02", **kw)

    def test_shopify_down_after_payment_keeps_the_bill_and_sync_creates_exactly_one_order(self):
        self.shopify.submit_order.side_effect = AmbiguousWriteError("u", TimeoutError())
        res = self._checkout()
        self.assertEqual(res["status"], "pending_sync")
        self.assertEqual(len(self.svc.outbox.pending()), 1)
        self.assertEqual(self.terminal.charge.call_count, 1)  # charged once

        self.shopify.submit_order.side_effect = None
        self.shopify.submit_order.return_value = order_record()
        out = self.svc.sync_pending()
        self.assertEqual(out[0]["status"], "synced")
        self.assertEqual(self.svc.outbox.pending(), [])
        self.assertTrue(self.shopify.submit_order.call_args[1]["check_existing_first"])
        self.assertEqual(self.svc.invoices.data["HSR"]["invoices"][0]["status"], "synced")
        self.assertEqual(self.svc.sync_pending(), [])  # nothing left to replay

    def test_terminal_decline_keeps_invoice_number_as_cancelled_and_next_bill_continues(self):
        self.terminal.charge.side_effect = RuntimeError("declined")
        with self.assertRaises(RuntimeError):
            self._checkout()
        inv = self.svc.invoices.data["HSR"]["invoices"]
        self.assertEqual((inv[0]["invoice_no"], inv[0]["status"]), ("ELU/HSR/FY26/00001", "cancelled"))
        self.terminal.charge.side_effect = None
        self.shopify.submit_order.return_value = order_record()
        self.assertEqual(self._checkout()["invoice_no"], "ELU/HSR/FY26/00002")
        self.shopify.submit_order.assert_called_once()  # no order for the cancelled bill

    def test_invoice_number_is_the_terminal_idempotency_key(self):
        self.shopify.submit_order.return_value = order_record()
        res = self._checkout()
        self.assertEqual(self.terminal.charge.call_args[1]["order_ref"], res["invoice_no"])

    def test_successful_bill_marks_synced_and_audits(self):
        self.shopify.submit_order.return_value = order_record()
        res = self._checkout()
        self.assertEqual(res["status"], "synced")
        self.assertEqual(self.svc.audit.events[-1]["what"], "ORDER_COMPLETED")
        self.assertEqual(self.svc.outbox.pending(), [])


if __name__ == "__main__":
    unittest.main()
