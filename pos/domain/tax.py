"""HSN-based GST calculation engine.

Calculates intra-state CGST + SGST backed out from inclusive MRP prices,
reconciling exactly to the paisa (taxable + CGST + SGST == gross).
All tax rates are data-driven from tax_rates.json with effective date ranges.
"""

import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from pos.config import TAX_RATES_FILE
from pos.domain.money import Money
from pos.domain.models import CartItem, TaxLine


class TaxRateRule:
    def __init__(self, hsn: str, description: str, rate_bps: int, effective_from: str, effective_to: Optional[str] = None):
        self.hsn = hsn
        self.description = description
        self.rate_bps = rate_bps  # basis points (e.g. 1800 for 18%, 500 for 5%)
        self.effective_from = effective_from
        self.effective_to = effective_to

    def applies_on(self, target_date: str) -> bool:
        if target_date < self.effective_from:
            return False
        if self.effective_to and target_date > self.effective_to:
            return False
        return True


class TaxCalculator:
    def __init__(self, tax_rates_path: Optional[Path] = None):
        self.path = tax_rates_path or TAX_RATES_FILE
        self.rules: List[TaxRateRule] = []
        self._load_rules()

    def _load_rules(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data.get("rates", []):
            self.rules.append(
                TaxRateRule(
                    hsn=r["hsn"],
                    description=r.get("description", ""),
                    rate_bps=int(r["rate_bps"]),
                    effective_from=r["effective_from"],
                    effective_to=r.get("effective_to"),
                )
            )

    def get_rate_bps(self, hsn: str, target_date: Optional[str] = None) -> int:
        """Find the effective tax rate in basis points for a given HSN and date."""
        check_date = target_date or date.today().isoformat()
        matches = [r for r in self.rules if r.hsn == hsn and r.applies_on(check_date)]
        if not matches:
            raise ValueError(f"No active tax rate found for HSN {hsn} on date {check_date}")
        if len({r.rate_bps for r in matches}) > 1:
            # Overlapping date ranges in tax_rates.json are a data error; refuse rather than guess.
            raise ValueError(f"Conflicting tax rates for HSN {hsn} on {check_date} in tax_rates.json")
        return matches[0].rate_bps

    @staticmethod
    def backout_tax(gross_paise: int, rate_bps: int) -> Tuple[int, int, int]:
        """Back out taxable value and intra-state tax split (taxable, CGST, SGST) in paise.

        Reconciles strictly to the paisa: taxable + cgst + sgst == gross_paise.
        """
        g = Decimal(gross_paise)
        taxable = int((g * 10000 / (10000 + rate_bps)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total_tax = gross_paise - taxable
        cgst = int((Decimal(total_tax) / Decimal(2)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        sgst = total_tax - cgst
        assert taxable + cgst + sgst == gross_paise, "Tax reconciliation invariant failed!"
        return taxable, cgst, sgst

    def apply_tax_to_line(self, item: CartItem, order_date: Optional[str] = None) -> None:
        """Calculate line taxable amount, CGST, and SGST, populating CartItem."""
        hsn = item.variant.hsn
        gross_paise = item.gross_amount.paise
        rate_bps = self.get_rate_bps(hsn, order_date)

        taxable_p, cgst_p, sgst_p = self.backout_tax(gross_paise, rate_bps)
        item.taxable_amount = Money(taxable_p)

        # Intra-state supply: rate split equally (e.g. 1800 bps -> CGST 900 + SGST 900)
        half_bps = rate_bps // 2
        item.tax_lines = [
            TaxLine(title="CGST", rate_bps=half_bps, price=Money(cgst_p)),
            TaxLine(title="SGST", rate_bps=rate_bps - half_bps, price=Money(sgst_p)),
        ]
