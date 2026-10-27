"""Adapter for Store Management Tool (SMT) handling prescriptions and staff."""

import urllib.parse
from typing import List, Optional
from pos.config import SMT_API_BASE
from pos.adapters.http_client import ResilientHttpClient
from pos.domain.models import Prescription, EyeRx, StaffMember


class SmtAdapter:
    """Communicates with Store Management Tool (SMT)."""

    def __init__(self, base_url: str = SMT_API_BASE, client: Optional[ResilientHttpClient] = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or ResilientHttpClient()

    def get_prescriptions(self, phone: str) -> List[Prescription]:
        """Fetch prescriptions for a customer by phone number, returned newest first."""
        encoded_phone = urllib.parse.quote(phone)
        url = f"{self.base_url}/prescriptions?phone={encoded_phone}"
        data = self.client.get(url)

        rx_list: List[Prescription] = []
        for r in data.get("prescriptions", []):
            od_data = r.get("od", {})
            os_data = r.get("os", {})

            od = EyeRx(
                sph=float(od_data.get("sph", 0.0)),
                cyl=float(od_data.get("cyl", 0.0)),
                axis=od_data.get("axis"),
                add=od_data.get("add"),
            )
            os = EyeRx(
                sph=float(os_data.get("sph", 0.0)),
                cyl=float(os_data.get("cyl", 0.0)),
                axis=os_data.get("axis"),
                add=os_data.get("add"),
            )

            rx_list.append(
                Prescription(
                    rx_id=r["rx_id"],
                    customer_id=r["customer_id"],
                    phone=r["phone"],
                    date=r["date"],
                    source=r.get("source", "in_store"),
                    optometrist_id=r.get("optometrist_id"),
                    od=od,
                    os=os,
                    pd=r.get("pd", {}),
                    valid_until=r["valid_until"],
                    notes=r.get("notes"),
                )
            )

        return rx_list

    def get_latest_valid_prescription(self, phone: str, target_date: Optional[str] = None) -> Optional[Prescription]:
        """Newest prescription that is valid on target_date (test date <= target <= valid_until).

        Returns None when there is none: the till must not silently fall back to an
        expired or future-dated prescription.
        """
        for rx in self.get_prescriptions(phone):
            if rx.is_valid_for_date(target_date):
                return rx
        return None

    def get_staff_members(self, store_code: Optional[str] = None) -> List[StaffMember]:
        """Fetch staff list, optionally filtered by store code."""
        url = f"{self.base_url}/staff"
        if store_code:
            url += f"?store={urllib.parse.quote(store_code)}"
        data = self.client.get(url)

        staff_list: List[StaffMember] = []
        for s in data.get("staff", []):
            staff_list.append(
                StaffMember(
                    staff_id=s["staff_id"],
                    name=s.get("name", s["staff_id"]),
                    role=s.get("role", "sales"),
                    store_code=s["store_code"],
                    can_override_discount=s.get("can_override_discount", False),
                    progressive_expert="progressive_expert" in s.get("badges", []),
                )
            )
        return staff_list

    def get_staff_member(self, staff_id: str) -> Optional[StaffMember]:
        """Look up one staff member by id (used to verify discount approvers)."""
        for member in self.get_staff_members():
            if member.staff_id == staff_id:
                return member
        return None
