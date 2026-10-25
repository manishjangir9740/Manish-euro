"""Clinical validation of a lens against the prescription."""
import unittest
from pos.domain.models import LensLimits
from pos.domain.rx_validator import PrescriptionValidator
from tests.helpers import lens, rx

V = PrescriptionValidator.validate_lens_choice


class TestRxValidator(unittest.TestCase):
    def setUp(self):
        self.lens = lens(limits=LensLimits(-6.0, 3.0, 2.0, True, 0.75, 3.0))

    def test_valid_rx_passes(self):
        res = V(self.lens, rx(), "2026-10-02", 80001005)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.errors, [])

    def test_sphere_out_of_range_blocked_with_actionable_reason(self):
        res = V(self.lens, rx(od=(-7.0, 0.0, None, 2.0)), "2026-10-02")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Right eye (OD) sphere -7.00D is outside" in e and "higher-index" in e for e in res.errors))

    def test_dr_iyer_case_156_index_for_minus_six(self):
        sv156 = lens(ltype="single_vision", index=1.56, coating="standard", limits=LensLimits(-4.0, 4.0, 2.0, False))
        res = V(sv156, rx(od=(-6.0, 0.0, None, None), os=(-6.0, 0.0, None, None)), "2026-10-02")
        self.assertFalse(res.is_valid)

    def test_cylinder_over_limit_blocked(self):
        res = V(self.lens, rx(os=(-1.0, -2.5, 90, 2.0)), "2026-10-02")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("cylinder" in e for e in res.errors))

    def test_missing_add_on_progressive_blocked_but_not_on_single_vision(self):
        no_add = rx(od=(-2.0, 0.0, None, None), os=(-2.0, 0.0, None, None))
        self.assertFalse(V(self.lens, no_add, "2026-10-02").is_valid)
        sv = lens(ltype="single_vision", limits=LensLimits(-6.0, 3.0, 2.0, False))
        self.assertTrue(V(sv, no_add, "2026-10-02").is_valid)

    def test_add_outside_lens_range_blocked(self):
        self.assertFalse(V(self.lens, rx(od=(-2.0, 0.0, None, 3.5)), "2026-10-02").is_valid)

    def test_expired_prescription_blocked(self):
        res = V(self.lens, rx(valid_until="2026-01-01"), "2026-10-02")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("expired on 2026-01-01" in e for e in res.errors))

    def test_valid_on_last_day_and_future_dated_rx_blocked(self):
        self.assertTrue(V(self.lens, rx(valid_until="2026-10-02"), "2026-10-02").is_valid)
        self.assertFalse(V(self.lens, rx(date="2026-12-01"), "2026-10-02").is_valid)

    def test_no_prescription_blocks_the_lens(self):
        res = V(self.lens, None, "2026-10-02")
        self.assertFalse(res.is_valid)
        self.assertIn("eye test", res.errors[0])

    def test_other_customers_prescription_blocked(self):
        self.assertFalse(V(self.lens, rx(cid=1), "2026-10-02", customer_id=80001005).is_valid)

    def test_cylinder_without_axis_blocked(self):
        self.assertFalse(V(self.lens, rx(od=(-1.0, -0.5, None, 2.0)), "2026-10-02").is_valid)

    def test_off_grid_axis_is_a_warning_for_optometrist_not_a_block(self):
        res = V(self.lens, rx(od=(-1.0, -0.5, 87, 2.0), os=(-1.0, -0.5, 92, 2.0), source="external"), "2026-10-02")
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.warnings), 2)
        self.assertTrue(all("5° grid" in w for w in res.warnings))

    def test_on_grid_axis_has_no_warning(self):
        res = V(self.lens, rx(od=(-1.0, -0.5, 90, 2.0), os=(-1.0, -0.5, 85, 2.0)), "2026-10-02")
        self.assertEqual(res.warnings, [])

    def test_suitable_lenses_only_returns_passing_options(self):
        low = lens(ltype="single_vision", index=1.5, coating="standard", vid=1, limits=LensLimits(-4.0, 4.0, 2.0, False))
        high = lens(ltype="single_vision", index=1.67, coating="standard", vid=2, limits=LensLimits(-10.0, 8.0, 4.0, False))
        strong = rx(od=(-6.0, 0.0, None, None), os=(-6.0, 0.0, None, None))
        out = PrescriptionValidator.suitable_lenses([low, high], strong, order_date="2026-10-02")
        self.assertEqual([v.id for v in out], [2])


if __name__ == "__main__":
    unittest.main()
