"""Offer engine: dates, conditions, stackability, best-for-customer, manager discount rules."""
import unittest
from pos.domain.models import Cart, CartItem, ManualDiscount, StaffMember
from pos.domain.money import Money
from pos.domain.offers import OfferEngine
from tests.helpers import customer, frame, lens, pair_cart


def ids(res):
    return {a.offer_id for a in res.applied_offers}


class TestOfferEngine(unittest.TestCase):
    def setUp(self):
        self.engine = OfferEngine()
        self.manager = StaffMember("S108", "Meera P.", "store_manager", "HSR", True)
        self.sales = StaffMember("S105", "Vikram R.", "sales", "HSR", False)

    def test_campaign_offer_alone_beats_stack_when_it_saves_more(self):
        cart = pair_cart(tags=["campaign:progressive_oct26"])
        res = self.engine.apply_offers_to_cart(cart, "2026-10-02")
        # PGX 15% = 1424.85 beats FREE_BLUECUT 1000 + BUNDLE 300 = 1300
        self.assertEqual(ids(res), {"PGX_CAMPAIGN15"})
        self.assertEqual(cart.items[1].discount.paise, 142485)
        self.assertEqual(cart.items[0].discount.paise, 0)

    def test_better_combination_is_chosen_for_priority_customer(self):
        cart = pair_cart(tags=["campaign:progressive_oct26", "priority"])
        res = self.engine.apply_offers_to_cart(cart, "2026-10-02")
        # FREE_BLUECUT 1000 + PRIORITY 500 + BUNDLE 300 = 1800 > PGX alone 1424.85
        self.assertEqual(ids(res), {"FREE_BLUECUT_PGX", "PRIORITY500", "BUNDLE300"})
        self.assertEqual(cart.total_discounts.paise, 180000)
        self.assertEqual(sum(a.amount.paise for a in res.applied_offers), 180000)

    def test_stackable_offers_combine(self):
        cart = pair_cart(tags=["priority"], lens_kwargs={"ltype": "single_vision", "coating": "standard"})
        res = self.engine.apply_offers_to_cart(cart, "2026-05-01")
        self.assertEqual(ids(res), {"BUNDLE300", "PRIORITY500"})
        self.assertEqual(cart.total_discounts.paise, 80000)

    def test_expired_and_switched_off_offers_never_apply(self):
        cart = pair_cart()
        res = self.engine.apply_offers_to_cart(cart, "2026-05-01")
        self.assertNotIn("MONSOON20", ids(res))
        self.assertNotIn("FESTIVE10", ids(res))  # not yet started
        ev = {e["offer_id"]: e for e in res.evaluations}
        self.assertFalse(ev["MONSOON20"]["applied"])
        self.assertIn("switched off", ev["MONSOON20"]["why"])
        self.assertIn("outside validity", ev["FESTIVE10"]["why"])

    def test_festive_is_non_stackable_and_loses_to_a_bigger_stack(self):
        cart = pair_cart(tags=["priority"], lens_kwargs={"ltype": "single_vision", "coating": "standard"})
        res = self.engine.apply_offers_to_cart(cart, "2026-10-05")
        # FESTIVE10 on frame = 1099.80 ; stack BUNDLE300 + PRIORITY500 = 800 -> Festive wins alone
        self.assertEqual(ids(res), {"FESTIVE10"})
        self.assertEqual(cart.total_discounts.paise, 109980)

    def test_second_pair_discount_targets_cheapest_lens(self):
        cart = Cart(customer=customer())
        cart.add_item(CartItem(variant=frame(), pair_ref="1"))
        cart.add_item(CartItem(variant=lens("9499.00"), pair_ref="1"))
        cart.add_item(CartItem(variant=frame(vid=2), pair_ref="2"))
        cart.add_item(CartItem(variant=lens("1999.00", "single_vision", 1.5, "blue_cut", vid=3), pair_ref="2"))
        res = self.engine.apply_offers_to_cart(cart, "2026-06-01")
        self.assertIn("SECONDPAIR50", ids(res))
        self.assertEqual(cart.items[3].discount.paise, 99950 + 30000)  # 50% of 1999.00 + BUNDLE on pair lens
        self.assertEqual(cart.items[1].discount.paise, 30000)

    def test_discount_never_exceeds_line_price(self):
        cart = Cart(customer=customer(["priority"]))
        cart.add_item(CartItem(variant=lens("200.00", "single_vision", 1.5, "standard", vid=5), pair_ref="1"))
        self.engine.apply_offers_to_cart(cart, "2026-06-01")
        self.assertLessEqual(cart.items[0].discount.paise, 20000)
        self.assertEqual(cart.items[0].gross_amount.paise, 0)

    def test_manager_discount_needs_manager_and_reason(self):
        manual = ManualDiscount(bps=1000, approver_id="S108", reason_code="WALKOUT_RISK")
        cart = Cart(customer=customer())
        cart.add_item(CartItem(variant=frame(), pair_ref="1"))
        res = self.engine.apply_offers_to_cart(cart, "2026-05-01", manual, self.sales)
        self.assertNotIn("MANAGER_OVERRIDE", ids(res))
        res = self.engine.apply_offers_to_cart(cart, "2026-05-01", None, None)
        self.assertNotIn("MANAGER_OVERRIDE", ids(res))
        res = self.engine.apply_offers_to_cart(cart, "2026-05-01", manual, self.manager)
        self.assertEqual(ids(res), {"MANAGER_OVERRIDE"})
        self.assertEqual(cart.total_discounts.paise, 109980)

    def test_manager_discount_is_capped_at_ten_percent(self):
        manual = ManualDiscount(bps=2500, approver_id="S108", reason_code="WALKOUT_RISK")
        cart = Cart(customer=customer())
        cart.add_item(CartItem(variant=frame(), pair_ref="1"))
        self.engine.apply_offers_to_cart(cart, "2026-05-01", manual, self.manager)
        self.assertEqual(cart.total_discounts.paise, 109980)

    def test_evaluation_explains_every_offer(self):
        res = self.engine.apply_offers_to_cart(pair_cart(), "2026-10-02")
        self.assertEqual({e["offer_id"] for e in res.evaluations}, {o.offer_id for o in self.engine.offers})
        self.assertTrue(all(e["why"] for e in res.evaluations))


if __name__ == "__main__":
    unittest.main()
