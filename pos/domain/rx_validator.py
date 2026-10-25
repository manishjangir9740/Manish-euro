"""Clinical prescription validation engine.

Ensures that customer prescription powers (Sphere, Cylinder, Axis, ADD)
fall strictly within the optical limits of the chosen lens variant.
Provides actionable, staff-friendly error messages to avoid lab remakes.

Errors block the lens. Warnings are shown to staff and must be confirmed by
the optometrist, but do not block (e.g. an external Rx with axis 87°).
"""

from datetime import date
from typing import Iterable, List, Optional
from pos.domain.models import Prescription, Variant


class RxValidationError(Exception):
    """Raised when a lens does not satisfy prescription clinical requirements."""

    def __init__(self, message: str, errors: Optional[List[str]] = None, alternatives: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors or []
        self.alternatives = alternatives or []


class RxValidationResult:
    def __init__(self, is_valid: bool, errors: List[str], warnings: List[str]):
        self.is_valid = is_valid
        self.errors = errors
        self.warnings = warnings

    def __bool__(self) -> bool:
        return self.is_valid


AXIS_GRID_DEG = 5


class PrescriptionValidator:
    """Clinical lens-to-prescription validator."""

    @classmethod
    def validate_lens_choice(
        cls,
        lens: Variant,
        rx: Optional[Prescription],
        order_date: Optional[str] = None,
        customer_id: Optional[int] = None,
    ) -> RxValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        if rx is None:
            return RxValidationResult(
                False,
                [f"No valid prescription on file for this customer. Book an eye test (or enter the "
                 f"external Rx in the store tool) before billing lens {lens.sku}."],
                [],
            )

        # 0. The prescription must belong to the customer on the bill
        if customer_id is not None and rx.customer_id != customer_id:
            errors.append(
                f"Prescription {rx.rx_id} belongs to another customer. Pick this customer's prescription."
            )

        # 1. Validity window: test date not in the future, valid_until not passed
        target = order_date or date.today().isoformat()
        if rx.valid_until < target:
            errors.append(
                f"Prescription {rx.rx_id} expired on {rx.valid_until}. "
                f"A new eye test is required before dispensing."
            )
        elif rx.date > target:
            errors.append(
                f"Prescription {rx.rx_id} is dated {rx.date}, which is after the bill date {target}. "
                f"Ask the optometrist to correct the test date in the store tool."
            )

        # If variant has no rx limits (e.g. frame or non-rx accessory), no lens limits apply
        limits = lens.rx_limits
        if not limits:
            return RxValidationResult(len(errors) == 0, errors, warnings)

        # 2. Check each eye (OD = Right, OS = Left)
        eyes = [("Right eye (OD)", rx.od), ("Left eye (OS)", rx.os)]
        for eye_name, eye_rx in eyes:
            if eye_rx.sph < limits.sph_min or eye_rx.sph > limits.sph_max:
                errors.append(
                    f"{eye_name} sphere {eye_rx.sph:+.2f}D is outside {lens.sku} ({lens.display_name}) range "
                    f"{limits.sph_min:+.2f}D to {limits.sph_max:+.2f}D. Choose a higher-index lens."
                )

            if abs(eye_rx.cyl) > limits.cyl_abs_max:
                errors.append(
                    f"{eye_name} cylinder {eye_rx.cyl:+.2f}D exceeds {lens.sku} limit of "
                    f"±{limits.cyl_abs_max:.2f}D. Choose a lens with a wider cylinder range."
                )

            if limits.add_required:
                if eye_rx.add is None or eye_rx.add <= 0:
                    errors.append(
                        f"{lens.sku} is a {lens.lens_type or 'multifocal'} lens and needs an ADD, but "
                        f"{eye_name} has no ADD on {rx.rx_id}. Use a single-vision lens or ask the optometrist."
                    )
                elif (limits.add_min is not None and eye_rx.add < limits.add_min) or (
                    limits.add_max is not None and eye_rx.add > limits.add_max
                ):
                    errors.append(
                        f"{eye_name} ADD {eye_rx.add:+.2f}D is outside {lens.sku} ADD range "
                        f"{limits.add_min:+.2f}D to {limits.add_max:+.2f}D."
                    )

            # 3. Axis checks
            if eye_rx.cyl != 0:
                if eye_rx.axis is None:
                    errors.append(f"{eye_name} has cylinder {eye_rx.cyl:+.2f}D but no axis. Ask the optometrist.")
                elif not (0 <= eye_rx.axis <= 180):
                    errors.append(f"{eye_name} axis {eye_rx.axis}° must be between 0° and 180°.")
                elif eye_rx.axis % AXIS_GRID_DEG != 0:
                    warnings.append(
                        f"{eye_name} axis {eye_rx.axis}° on {rx.source} Rx {rx.rx_id} is not on the "
                        f"{AXIS_GRID_DEG}° grid. Optometrist to confirm before the lab order."
                    )

        return RxValidationResult(is_valid=(len(errors) == 0), errors=errors, warnings=warnings)

    @classmethod
    def suitable_lenses(
        cls,
        lenses: Iterable[Variant],
        rx: Prescription,
        lens_type: Optional[str] = None,
        coating: Optional[str] = None,
        order_date: Optional[str] = None,
    ) -> List[Variant]:
        """Lenses from the matrix that would pass validation, cheapest first."""
        out = []
        for v in lenses:
            if lens_type and v.lens_type != lens_type:
                continue
            if coating and v.coating != coating:
                continue
            if cls.validate_lens_choice(v, rx, order_date).is_valid:
                out.append(v)
        return sorted(out, key=lambda v: v.price.paise)
