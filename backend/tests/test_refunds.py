"""Refund math: tax reversed per line, frame restocked at the billing store, lens scrapped, credit notes."""
import unittest
from unittest.mock import MagicMock

from pos.domain.models import RefundRecord
from pos.domain.money import Money
from pos.domain.refunds import RefundError, plan_refund
from tests.helpers import make_service, order_record, tmpdir


class TestRefundPlan(unittest.TestCase):
    def test_full_refund_reverses_tax_per_line_and_totals_to_captured(self):
        plan = plan_refund(order_record())
        self.assertEqual(plan.amount.paise, 1907215)
        self.assertEqual(plan.tax.paise, 167766 + 38448)
        self.assertEqual(plan.taxable.paise, 1907215 - 206214)
        self.assertTrue(plan.is_full)
        self.assertEqual([l.tax.paise for l in plan.lines], [167766, 38448])

    def test_frame_restocks_at_billing_store_lens_does_not(self):
        frame_l, lens_l = plan_refund(order_record()).lines
        self.assertTrue(frame_l.restock)
        self.assertEqual(frame_l.location_id, 70000002)
        self.assertFalse(lens_l.restock)
        self.assertIsNone(lens_l.location_id)

    def test_partial_refund_frame_only_and_lens_only(self):
        frame_only = plan_refund(order_record(), [96000001])
        self.assertEqual(frame_only.amount.paise, 1099800)
        self.assertFalse(frame_only.is_full)
        lens_only = plan_refund(order_record(), [96000002])
        self.assertEqual(lens_only.amount.paise, 807415)
        self.assertEqual(lens_only.tax.paise, 38448)

    def test_second_partial_refund_cannot_repeat_a_line_and_completes_the_rest(self):
        done = RefundRecord(1, "", Money(1099800), Money(167766), "CN1", [96000001])
        order = order_record(refunds=[done])
        with self.assertRaises(RefundError):
            plan_refund(order, [96000001])
        rest = plan_refund(order)
        self.assertEqual([l.line_id for l in rest.lines], [96000002])
        self.assertTrue(rest.is_full)

    def test_fully_refunded_and_cancelled_orders_are_rejected(self):
        done = RefundRecord(1, "", Money(1907215), Money(206214), "CN1", [96000001, 96000002])
        with self.assertRaises(RefundError):
            plan_refund(order_record(refunds=[done]))
        with self.assertRaises(RefundError):
            plan_refund(order_record(cancelled=True))

    def test_unknown_line_rejected(self):
        with self.assertRaises(RefundError):
            plan_refund(order_record(), [1])


class TestRefundService(unittest.TestCase):
    def setUp(self):
        self._d, self.tmp = tmpdir()
        self.addCleanup(self._d.cleanup)
        self.shopify, self.terminal = MagicMock(), MagicMock()
        self.shopify.get_order.return_value = order_record()
        self.shopify.calculate_refund.return_value = (Money(1907215), Money(206214))
        self.shopify.create_refund.return_value = RefundRecord(7, "", Money(1907215), Money(206214), "x", [])
        self.svc = make_service(self.tmp, self.shopify, self.terminal)

    def test_full_refund_records_credit_note_terminal_refund_and_shopify_refund(self):
        res = self.svc.process_refund(95000001, "S105", "CHANGED_MIND")
        self.assertEqual(res["credit_note_no"], "ELU/HSR/FY26/CN/00001")
        self.assertEqual(res["original_invoice_no"], "ELU/HSR/FY26/00001")
        self.terminal.refund.assert_called_once_with("chg_1", Money(1907215), "CHANGED_MIND")
        plan, cn_no, reason, staff, method = self.shopify.create_refund.call_args[0]
        self.assertEqual((cn_no, reason, method), ("ELU/HSR/FY26/CN/00001", "CHANGED_MIND", "upi"))

    def test_credit_notes_are_sequential_per_store(self):
        self.svc.process_refund(95000001, "S105")
        self.assertEqual(self.svc.process_refund(95000001, "S105")["credit_note_no"], "ELU/HSR/FY26/CN/00002")

    def test_cash_refund_leaves_drawer_and_skips_terminal(self):
        self.shopify.get_order.return_value = order_record(payment="cash")
        s = self.svc.till.open_session("HSR", 70000002, "S108", Money(300000), "T1")
        self.svc.process_refund(95000001, "S105", till_session_id="T1")
        self.terminal.refund.assert_not_called()
        mv = self.svc.till.get_session("T1")["movements"][0]
        self.assertEqual((mv["type"], mv["amount_paise"]), ("cash_refund", -1907215))

    def test_pos_and_shopify_disagreeing_blocks_the_refund(self):
        self.shopify.calculate_refund.return_value = (Money(1907200), Money(0))
        with self.assertRaises(ValueError):
            self.svc.process_refund(95000001, "S105")
        self.shopify.create_refund.assert_not_called()
        self.terminal.refund.assert_not_called()

    def test_failed_refund_marks_credit_note_cancelled_and_is_audited(self):
        self.shopify.create_refund.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            self.svc.process_refund(95000001, "S105")
        cn = self.svc.invoices.data["HSR"]["credit_notes"][0]
        self.assertEqual(cn["status"], "cancelled")
        self.assertEqual(self.svc.audit.events[-1]["what"], "REFUND_FAILED")

    def test_unknown_reason_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.process_refund(95000001, "S105", "BECAUSE")


if __name__ == "__main__":
    unittest.main()
