"""Invoice series, cash till, manager-discount audit rules, and the day-end report."""
import unittest
from unittest.mock import MagicMock

from pos.domain.invoice_series import InvoiceSeriesManager
from pos.domain.models import RefundRecord, StaffMember
from pos.domain.money import Money
from pos.domain.rx_validator import RxValidationError
from pos.domain.till import TillSessionManager
from tests.helpers import make_service, order_record, pair_cart, rx, tmpdir


class TestInvoiceSeries(unittest.TestCase):
    def setUp(self):
        self._d, self.tmp = tmpdir()
        self.addCleanup(self._d.cleanup)
        self.s = InvoiceSeriesManager(self.tmp / "s.json")

    def test_sequential_gapless_and_independent_per_store(self):
        self.assertEqual([self.s.next_invoice_number("HSR") for _ in range(3)],
                         [f"ELU/HSR/FY26/0000{i}" for i in (1, 2, 3)])
        self.assertEqual(self.s.next_invoice_number("JN"), "ELU/JN/FY26/00001")

    def test_cancelled_number_stays_in_series_and_is_not_reused(self):
        a = self.s.next_invoice_number("HSR")
        self.s.record_cancelled("HSR", a, "payment failed")
        b = self.s.next_invoice_number("HSR")
        self.assertEqual((a, b), ("ELU/HSR/FY26/00001", "ELU/HSR/FY26/00002"))
        self.assertEqual([r["status"] for r in self.s.data["HSR"]["invoices"]], ["cancelled", "issued"])

    def test_persists_across_instances(self):
        self.s.next_invoice_number("HSR")
        self.assertEqual(InvoiceSeriesManager(self.tmp / "s.json").next_invoice_number("HSR"), "ELU/HSR/FY26/00002")

    def test_credit_note_series_references_original_invoice(self):
        cn = self.s.next_credit_note_number("HSR", "ELU/HSR/FY26/00001")
        self.assertEqual(cn, "ELU/HSR/FY26/CN/00001")
        self.assertEqual(self.s.data["HSR"]["credit_notes"][0]["original_invoice_no"], "ELU/HSR/FY26/00001")

    def test_new_store_series_continues_after_numbers_already_in_shopify(self):
        self.s.start_after("HSR", "ELU/HSR/FY26/", 2, 1)
        self.assertEqual(self.s.next_invoice_number("HSR"), "ELU/HSR/FY26/00003")
        self.assertEqual(self.s.next_credit_note_number("HSR"), "ELU/HSR/FY26/CN/00002")
        self.s.start_after("HSR", "ELU/HSR/FY26/", 1, 0)  # never moves backwards
        self.assertEqual(self.s.next_invoice_number("HSR"), "ELU/HSR/FY26/00004")

    def test_checkout_starts_series_after_shopify_history(self):
        shopify = MagicMock()
        svc = make_service(self.tmp, shopify)
        shopify.last_document_numbers.return_value = (2, 0)
        shopify.build_order_payload.return_value = {"order": {}}
        shopify.submit_order.return_value = order_record()
        svc.terminal.charge.return_value = {"charge_id": "c1", "status": "captured"}
        self.assertEqual(svc.checkout(pair_cart(), "HSR", "S105", "upi", order_date="2026-10-02")["invoice_no"],
                         "ELU/HSR/FY26/00003")

    def test_cancelling_unknown_invoice_is_an_error(self):
        with self.assertRaises(ValueError):
            self.s.record_cancelled("HSR", "ELU/HSR/FY26/00099", "x")


class TestTill(unittest.TestCase):
    def setUp(self):
        self._d, self.tmp = tmpdir()
        self.addCleanup(self._d.cleanup)
        self.t = TillSessionManager(self.tmp / "t.json")
        self.t.open_session("JN", 70000005, "S120", Money(300000), "T1")

    def test_seed_day_short_by_250_is_flagged(self):
        for typ, amt, reason in [("cash_sale", 899800, None), ("cash_sale", 549800, None),
                                 ("paid_out", 12000, "courier"), ("paid_out", 8000, "tea/snacks"),
                                 ("paid_in", 100000, "change from HQ")]:
            self.t.record_cash_movement("T1", typ, Money(amt), "r", reason)
        s = self.t.close_session("T1", "S120", Money(1804600))
        self.assertEqual(s["expected_cash_paise"], 1829600)
        self.assertEqual(s["variance_paise"], -25000)
        self.assertTrue(s["variance_alert"])
        self.assertIn("ALERT", s["variance_note"])

    def test_variance_within_200_is_not_flagged(self):
        s = self.t.close_session("T1", "S120", Money(300000 - 20000))
        self.assertFalse(s["variance_alert"])
        self.assertEqual(s["variance_paise"], -20000)

    def test_paid_out_needs_reason_and_reduces_expected(self):
        with self.assertRaises(ValueError):
            self.t.record_cash_movement("T1", "paid_out", Money(5000), "r")
        self.t.record_cash_movement("T1", "paid_out", Money(5000), "r", "courier")
        self.assertEqual(self.t.get_session("T1")["expected_cash_paise"], 295000)

    def test_closed_session_rejects_movements_and_second_close(self):
        self.t.close_session("T1", "S120", Money(300000))
        with self.assertRaises(ValueError):
            self.t.record_cash_movement("T1", "paid_in", Money(1), "r", "x")
        with self.assertRaises(ValueError):
            self.t.close_session("T1", "S120", Money(300000))


class TestManagerDiscountAudit(unittest.TestCase):
    def setUp(self):
        self._d, self.tmp = tmpdir()
        self.addCleanup(self._d.cleanup)
        self.smt = MagicMock()
        self.shopify = MagicMock()
        self.svc = make_service(self.tmp, self.shopify, smt=self.smt)

    def _resolve(self, approver, bps=1000, reason="WALKOUT_RISK", approver_id="S108"):
        self.smt.get_staff_member.return_value = approver
        return self.svc._resolve_manual_discount("HSR", bps, approver_id, reason)

    def test_requires_approver_and_reason_code(self):
        with self.assertRaises(ValueError):
            self.svc._resolve_manual_discount("HSR", 1000, None, "WALKOUT_RISK")
        with self.assertRaises(ValueError):
            self.svc._resolve_manual_discount("HSR", 1000, "S108", None)

    def test_over_ten_percent_and_unknown_reason_rejected(self):
        mgr = StaffMember("S108", "M", "store_manager", "HSR", True)
        with self.assertRaises(ValueError):
            self._resolve(mgr, bps=1001)
        with self.assertRaises(ValueError):
            self._resolve(mgr, reason="BECAUSE")

    def test_sales_staff_other_store_manager_and_unknown_staff_rejected(self):
        with self.assertRaises(ValueError):
            self._resolve(StaffMember("S105", "S", "sales", "HSR", False), approver_id="S105")
        with self.assertRaises(ValueError):
            self._resolve(StaffMember("S120", "T", "store_manager", "JN", True), approver_id="S120")
        with self.assertRaises(ValueError):
            self._resolve(None)

    def test_valid_manager_accepted(self):
        manual, approver = self._resolve(StaffMember("S108", "M", "store_manager", "HSR", True))
        self.assertEqual((manual.bps, manual.approver_id, manual.reason_code), (1000, "S108", "WALKOUT_RISK"))

    def test_checkout_blocks_lens_without_valid_prescription(self):
        cart = pair_cart(with_rx=rx(valid_until="2026-01-01"))
        with self.assertRaises(RxValidationError):
            self.svc.checkout(cart, "HSR", "S105", "upi", order_date="2026-10-02")
        self.assertEqual(self.svc.invoices.data, {})  # no invoice number burned


class TestDayEnd(unittest.TestCase):
    def setUp(self):
        self._d, self.tmp = tmpdir()
        self.addCleanup(self._d.cleanup)
        self.shopify = MagicMock()
        self.svc = make_service(self.tmp, self.shopify)

    def test_totals_refunds_payment_split_and_channel(self):
        refund = RefundRecord(1, "", Money(1099800), Money(167766), "CN1", [96000001])
        a = order_record(refunds=[refund])
        b = order_record(payment="cash", order_id=2)
        b.channel, b.invoice_no = "walk_in", "ELU/HSR/FY26/00002"
        self.shopify.orders_for_location.return_value = [a, b]
        r = self.svc.generate_day_end_report("HSR", "2026-10-02")
        self.assertEqual(r["bill_count"], 2)
        self.assertEqual(r["gross_sales"].paise, 2 * 2049700)
        self.assertEqual(r["total_discounts"].paise, 2 * 142485)
        self.assertEqual(r["total_tax"].paise, 2 * 206214)
        self.assertEqual(r["total_taxable"].paise, 2 * (1907215 - 206214))
        self.assertEqual(r["net_billed"].paise, 2 * 1907215)
        self.assertEqual(r["total_refunds"].paise, 1099800)
        self.assertEqual(r["payment_splits"]["upi"].paise, 1907215)
        self.assertEqual(r["payment_net"]["upi"].paise, 1907215 - 1099800)
        self.assertEqual(r["payment_net"]["cash"].paise, 1907215)
        self.assertEqual(r["channel_splits"], {"whatsapp_booked": 1, "walk_in": 1})
        # taxable + tax == net billed, to the paisa
        self.assertEqual((r["total_taxable"] + r["total_tax"]).paise, r["net_billed"].paise)

    def test_cancelled_orders_are_excluded(self):
        self.shopify.orders_for_location.return_value = [order_record(), order_record(cancelled=True, order_id=3)]
        self.assertEqual(self.svc.generate_day_end_report("HSR", "2026-10-02")["bill_count"], 1)

    def test_paid_invoice_missing_from_shopify_and_till_mismatch_are_shown(self):
        self.svc.invoices.next_invoice_number("HSR", bill_date="2026-10-02")  # 00001 issued, not synced
        self.svc.invoices.next_invoice_number("HSR", bill_date="2026-10-02")  # 00002 issued, not synced
        self.shopify.orders_for_location.return_value = [order_record(payment="cash")]  # has 00001 only
        self.svc.till.open_session("HSR", 70000002, "S108", Money(300000), "TILL-HSR-2026-10-02")
        self.svc.till.sessions["TILL-HSR-2026-10-02"]["opened_at"] = "2026-10-02T10:00:00+05:30"
        self.svc.till._save()
        r = self.svc.generate_day_end_report("HSR", "2026-10-02")
        text = " | ".join(r["mismatches"])
        self.assertIn("00002", text)
        self.assertNotIn("00001 is paid", text)
        self.assertIn("cash sales: till", text)
        self.assertIn("MISMATCH", r["report_text"])

    def test_clean_day_reports_ok(self):
        self.shopify.orders_for_location.return_value = []
        r = self.svc.generate_day_end_report("HSR", "2026-10-02")
        self.assertEqual(r["mismatches"], [])
        self.assertIn("OK: invoice register", r["report_text"])


if __name__ == "__main__":
    unittest.main()
