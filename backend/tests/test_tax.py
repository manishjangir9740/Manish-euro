"""GST: taxable + CGST + SGST == gross to the paisa, date-effective rates, per-line tax lines."""
import unittest
from pos.domain.models import CartItem
from pos.domain.money import Money
from pos.domain.tax import TaxCalculator
from tests.helpers import frame, lens


class TestTaxCalculator(unittest.TestCase):
    def setUp(self):
        self.tax = TaxCalculator()

    def test_sample_invoice_frame_tax(self):
        self.assertEqual(self.tax.backout_tax(1099800, 1800), (932034, 83883, 83883))

    def test_sample_invoice_lens_tax(self):
        self.assertEqual(self.tax.backout_tax(807415, 500), (768967, 19224, 19224))

    def test_odd_tax_paisa_goes_to_sgst(self):
        taxable, cgst, sgst = self.tax.backout_tax(807416, 500)
        self.assertEqual(taxable + cgst + sgst, 807416)
        self.assertLessEqual(abs(cgst - sgst), 1)

    def test_paisa_invariance_across_range(self):
        for p in range(1, 60000, 7):
            for bps in (500, 1200, 1800, 2800):
                t, c, s = self.tax.backout_tax(p, bps)
                self.assertEqual(t + c + s, p)

    def test_date_effective_rates(self):
        self.assertEqual(self.tax.get_rate_bps("90015000", "2026-10-01"), 500)
        self.assertEqual(self.tax.get_rate_bps("90015000", "2024-01-01"), 1200)
        self.assertEqual(self.tax.get_rate_bps("90015000", "2025-09-21"), 1200)
        self.assertEqual(self.tax.get_rate_bps("90015000", "2025-09-22"), 500)

    def test_unknown_hsn_is_an_error_not_zero_tax(self):
        with self.assertRaises(ValueError):
            self.tax.get_rate_bps("00000000", "2026-10-01")

    def test_line_tax_lines_match_sample_order(self):
        item = CartItem(variant=lens())
        item.discount = Money(142485)
        self.tax.apply_tax_to_line(item, "2026-10-02")
        self.assertEqual([t.price.paise for t in item.tax_lines], [19224, 19224])
        self.assertEqual([t.rate_bps for t in item.tax_lines], [250, 250])
        self.assertEqual(item.taxable_amount.paise, 768967)

    def test_frame_line_rate_is_nine_percent_each(self):
        item = CartItem(variant=frame())
        self.tax.apply_tax_to_line(item, "2026-10-02")
        self.assertEqual([t.rate for t in item.tax_lines], [0.09, 0.09])


if __name__ == "__main__":
    unittest.main()
