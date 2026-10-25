"""Cash drawer and till session management.

Supports opening session with a float, tracking cash sales, cash refunds,
paid-ins, paid-outs with reasons, counted close, and flags variance > ₹200 to Finance.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from pos.config import TILL_SESSIONS_FILE, TILL_VARIANCE_ALERT_PAISE
from pos.domain.filelock import locked, read_json, write_json_atomic
from pos.domain.money import Money

MOVEMENT_TYPES = ("cash_sale", "cash_refund", "paid_in", "paid_out")


class TillSessionManager:
    """Manages cash till drawer sessions for store POS."""

    def __init__(self, persistence_file: Optional[Path] = None):
        self.file_path = Path(persistence_file or TILL_SESSIONS_FILE)
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        self.sessions = read_json(self.file_path, {})

    def _save(self) -> None:
        write_json_atomic(self.file_path, self.sessions)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    @locked
    def import_sessions(self, sessions: List[Dict[str, Any]]) -> int:
        """Load sessions (e.g. till_sessions_sample.json) without overwriting existing ones."""
        self._ensure_loaded()
        added = 0
        for s in sessions:
            if s["session_id"] not in self.sessions:
                self.sessions[s["session_id"]] = s
                added += 1
        self._save()
        return added

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        return self.sessions.get(session_id)

    def find_session(self, store_code: str, day: str) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        for s in self.sessions.values():
            if s["store_code"] == store_code and s["opened_at"][:10] == day:
                return s
        return None

    @locked
    def open_session(
        self,
        store_code: str,
        location_id: int,
        staff_id: str,
        opening_float: Money,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open a new cash drawer session (one per store per day)."""
        self._ensure_loaded()
        now_iso = self._now()
        sid = session_id or f"TILL-{store_code}-{now_iso[:10]}"

        existing = self.sessions.get(sid)
        if existing:
            if existing.get("closed_at"):
                raise ValueError(f"Till session {sid} is already closed for today")
            return existing

        session = {
            "session_id": sid,
            "location_id": location_id,
            "store_code": store_code,
            "opened_at": now_iso,
            "opened_by": staff_id,
            "opening_float_paise": opening_float.paise,
            "movements": [],
            "closed_at": None,
            "closed_by": None,
            "expected_cash_paise": opening_float.paise,
            "counted_cash_paise": None,
            "variance_paise": None,
            "variance_note": None,
            "variance_alert": False,
        }
        self.sessions[sid] = session
        self._save()
        return session

    @locked
    def record_cash_movement(
        self,
        session_id: str,
        movement_type: str,  # 'cash_sale', 'cash_refund', 'paid_in', 'paid_out'
        amount: Money,
        ref: str,
        reason: Optional[str] = None,
        staff_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record cash movement in the drawer. Paid-ins and paid-outs need a reason."""
        self._ensure_loaded()
        if movement_type not in MOVEMENT_TYPES:
            raise ValueError(f"Unknown movement type '{movement_type}'")
        if movement_type in ("paid_in", "paid_out") and not reason:
            raise ValueError(f"A reason is required for {movement_type} (e.g. courier, tea/snacks)")
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Till session {session_id} not found")
        if session.get("closed_at"):
            raise ValueError(f"Till session {session_id} is already closed")

        # Cash leaving the drawer is negative, cash coming in is positive
        amt_paise = abs(amount.paise)
        if movement_type in ("paid_out", "cash_refund"):
            amt_paise = -amt_paise

        movement = {
            "type": movement_type,
            "amount_paise": amt_paise,
            "ref": ref,
            "at": self._now(),
            "reason": reason,
            "staff_id": staff_id,
        }
        session["movements"].append(movement)
        session["expected_cash_paise"] = session["opening_float_paise"] + sum(
            m["amount_paise"] for m in session["movements"]
        )
        self._save()
        return movement

    @locked
    def close_session(
        self,
        session_id: str,
        staff_id: str,
        counted_cash: Money,
        variance_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Close till session, calculate cash variance, and flag if |variance| > ₹200."""
        self._ensure_loaded()
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Till session {session_id} not found")
        if session.get("closed_at"):
            raise ValueError(f"Till session {session_id} is already closed")

        expected = session["opening_float_paise"] + sum(
            m["amount_paise"] for m in session["movements"]
        )
        counted = counted_cash.paise
        variance = counted - expected

        session["closed_at"] = self._now()
        session["closed_by"] = staff_id
        session["expected_cash_paise"] = expected
        session["counted_cash_paise"] = counted
        session["variance_paise"] = variance
        session["variance_alert"] = abs(variance) > TILL_VARIANCE_ALERT_PAISE

        if session["variance_alert"]:
            flag = (f"ALERT to Finance: variance {Money(variance).format_inr()} exceeds "
                    f"{Money(TILL_VARIANCE_ALERT_PAISE).format_inr()} threshold.")
            session["variance_note"] = f"{flag} {variance_note or ''}".strip()
        else:
            session["variance_note"] = variance_note

        self._save()
        return session
