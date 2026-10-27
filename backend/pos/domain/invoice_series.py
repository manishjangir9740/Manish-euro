"""Gapless sequential per-store invoice and credit note series.

Meets Vikram's compliance requirement:
- Gapless sequential numbers per store location, independent of Shopify's global order_number
- Separate credit note series per store, each credit note referencing the original invoice
- A number is never reused or dropped: if a bill fails after its number was allocated
  (e.g. the terminal declined), the number stays in the series marked "cancelled".

Numbers are allocated only after the cart is priced and validated, immediately before
the terminal charge, so the only way to burn a number is a failed payment, which is
exactly the case finance wants to see as "cancelled".
"""

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from pos.config import INVOICE_SEQUENCE_FILE
from pos.domain.filelock import locked, read_json, write_json_atomic

ISSUED = "issued"          # number allocated, bill in progress / pending Shopify sync
SYNCED = "synced"          # order exists in the system of record
CANCELLED = "cancelled"    # bill did not complete; number kept in series as cancelled




class InvoiceSeriesManager:
    """Manages sequential gapless invoice numbers and credit notes per store."""

    def __init__(self, persistence_file: Optional[Path] = None):
        self.file_path = Path(persistence_file or INVOICE_SEQUENCE_FILE)
        self.data: Dict[str, Dict[str, Any]] = {}
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        self.data = read_json(self.file_path, {})

    def _save(self) -> None:
        write_json_atomic(self.file_path, self.data)

    def _store(self, store_code: str, prefix: Optional[str] = None) -> Dict[str, Any]:
        entry = self.data.setdefault(store_code, {})
        entry.setdefault("prefix", prefix or f"ELU/{store_code}/FY26/")
        entry.setdefault("next_invoice_seq", 1)
        entry.setdefault("next_cn_seq", 1)
        entry.setdefault("invoices", [])
        entry.setdefault("credit_notes", [])
        return entry

    def has_store(self, store_code: str) -> bool:
        self._ensure_loaded()
        return store_code in self.data

    @locked
    def start_after(self, store_code: str, prefix: str, last_invoice_seq: int, last_cn_seq: int) -> None:
        """First use of a store: continue after what the system of record already holds."""
        self._ensure_loaded()
        entry = self._store(store_code, prefix)
        entry["next_invoice_seq"] = max(entry["next_invoice_seq"], last_invoice_seq + 1)
        entry["next_cn_seq"] = max(entry["next_cn_seq"], last_cn_seq + 1)
        self._save()

    @locked
    def next_invoice_number(
        self, store_code: str, prefix: Optional[str] = None, bill_date: Optional[str] = None
    ) -> str:
        """Allocate the next sequential gapless invoice number for a store."""
        self._ensure_loaded()
        entry = self._store(store_code, prefix)
        seq = entry["next_invoice_seq"]
        entry["next_invoice_seq"] = seq + 1
        inv_no = f"{entry['prefix']}{seq:05d}"
        entry["invoices"].append({
            "invoice_no": inv_no,
            "date": bill_date or date.today().isoformat(),
            "status": ISSUED,
            "reason": None,
        })
        self._save()
        return inv_no

    def _find(self, store_code: str, invoice_no: str) -> Optional[Dict[str, Any]]:
        for rec in self._store(store_code)["invoices"]:
            if rec["invoice_no"] == invoice_no:
                return rec
        return None

    @locked
    def mark_synced(self, store_code: str, invoice_no: str) -> None:
        self._ensure_loaded()
        rec = self._find(store_code, invoice_no)
        if rec:
            rec["status"] = SYNCED
            self._save()

    @locked
    def record_cancelled(self, store_code: str, invoice_no: str, reason: str) -> None:
        """Mark an invoice number as cancelled. It stays in the statutory series."""
        self._ensure_loaded()
        rec = self._find(store_code, invoice_no)
        if rec is None:
            raise ValueError(f"Invoice {invoice_no} was never issued for store {store_code}")
        rec["status"] = CANCELLED
        rec["reason"] = reason
        self._save()

    @locked
    def next_credit_note_number(
        self, store_code: str, original_invoice_no: Optional[str] = None, cn_date: Optional[str] = None
    ) -> str:
        """Allocate the next sequential gapless credit note number for a store."""
        self._ensure_loaded()
        entry = self._store(store_code)
        seq = entry["next_cn_seq"]
        entry["next_cn_seq"] = seq + 1
        cn_no = f"{entry['prefix']}CN/{seq:05d}"
        entry["credit_notes"].append({
            "credit_note_no": cn_no,
            "original_invoice_no": original_invoice_no,
            "date": cn_date or date.today().isoformat(),
            "status": ISSUED,
        })
        self._save()
        return cn_no

    @locked
    def mark_credit_note(self, store_code: str, cn_no: str, status: str) -> None:
        self._ensure_loaded()
        for rec in self._store(store_code)["credit_notes"]:
            if rec["credit_note_no"] == cn_no:
                rec["status"] = status
        self._save()

    def invoices_for(self, store_code: str, bill_date: Optional[str] = None) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        if store_code not in self.data:
            return []
        rows = self._store(store_code)["invoices"]
        return [r for r in rows if bill_date is None or r["date"] == bill_date]
