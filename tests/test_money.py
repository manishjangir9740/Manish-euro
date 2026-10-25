"""Unit tests for the Money value object."""
import unittest
from pos.domain.money import Money


class TestMoney(unittest.TestCase):
    def test_paise_conversion(self):
        m = Money.from_decimal("104.98")
        self.assertEqual(m.paise, 10498)
        self.assertEqual(m.to_decimal(), "104.98")

    def test_zero_and_negative(self):
        self.assertEqual(Money.zero().to_decimal(), "0.00")
        self.assertEqual(Money(-25000).to_decimal(), "-250.00")
        self.assertEqual(Money(-25000).format_inr(), "-₹250.00")

    def test_arithmetic(self):
        a, b = Money(5000), Money(2550)
        self.assertEqual((a + b).paise, 7550)
        self.assertEqual((a - b).paise, 2450)
        self.assertEqual((a * 2).paise, 10000)

    def test_rejects_float_paise(self):
        with self.assertRaises(TypeError):
            Money(10.5)

    def test_percent_bps_rounds_half_up_in_integers(self):
        self.assertEqual(Money.from_decimal("9499.00").percent_bps(1500).paise, 142485)  # 15%
        self.assertEqual(Money(5).percent_bps(1000).paise, 1)   # 0.5 paise -> 1
        self.assertEqual(Money(4).percent_bps(1000).paise, 0)   # 0.4 paise -> 0
        self.assertEqual(Money(1099800).percent_bps(1000).paise, 109980)

    def test_allocate_sums_exactly(self):
        parts = Money(50000).allocate([1099800, 949900])
        self.assertEqual(sum(p.paise for p in parts), 50000)
        self.assertEqual([p.paise for p in Money(100).allocate([1, 1, 1])], [34, 33, 33])

    def test_format_inr(self):
        self.assertEqual(Money.from_decimal("19072.15").format_inr(), "₹19,072.15")
        self.assertEqual(Money.from_decimal("1234567.00").format_inr(), "₹12,34,567.00")

    def test_to_words(self):
        self.assertIn("nineteen thousand seventy-two rupees and fifteen paise",
                      Money.from_decimal("19072.15").to_words().lower())


if __name__ == "__main__":
    unittest.main()
