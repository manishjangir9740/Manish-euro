"""Local write-ahead journal ("outbox") for bills that must reach the system of record.

Farhan's Koramangala case: Wi-Fi drops mid-bill. The customer has paid on the terminal,
but the Shopify order create times out. The bill must not vanish and must not be
created twice when the connection comes back.

Flow:
1. Before the order create, the POS writes {invoice_no, charge, order payload} here.
2. On success the entry is marked synced.
3. On failure it stays "pending"; `run_pos.py sync-pending` replays it. Each replay
   first asks the backend whether an order with that invoice_no already exists
   (the idempotency key), so a create that actually succeeded is never repeated.

The payload is opaque to this module: it is whatever the backend adapter needs.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pos.config import OUTBOX_FILE
from pos.domain.filelock import file_lock, read_json, write_json_atomic

def _locked(method):
    import functools

    @functools.wraps(method)
    def wrapper(self, *a, **kw):
        with file_lock(self.file_path):
            return method(self, *a, **kw)
    return wrapper


PENDING = "pending"
SYNCED = "synced"


class BillOutbox:
    def __init__(self, persistence_file: Optional[Path] = None):
        self.file_path = Path(persistence_file or OUTBOX_FILE)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        return read_json(self.file_path, {})

    def _save(self, data: Dict[str, Dict[str, Any]]) -> None:
        write_json_atomic(self.file_path, data)

    @_locked
    def record(self, invoice_no: str, entry: Dict[str, Any]) -> None:
        data = self._load()
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        data[invoice_no] = {**entry, "invoice_no": invoice_no, "status": PENDING,
                            "attempts": 0, "last_error": None, "recorded_at": now}
        self._save(data)

    @_locked
    def mark_attempt_failed(self, invoice_no: str, error: str) -> None:
        data = self._load()
        if invoice_no in data:
            data[invoice_no]["attempts"] += 1
            data[invoice_no]["last_error"] = error
            self._save(data)

    @_locked
    def mark_synced(self, invoice_no: str, order_id: Any) -> None:
        data = self._load()
        if invoice_no in data:
            data[invoice_no]["status"] = SYNCED
            data[invoice_no]["order_id"] = order_id
            self._save(data)

    def get(self, invoice_no: str) -> Optional[Dict[str, Any]]:
        return self._load().get(invoice_no)

    def pending(self) -> List[Dict[str, Any]]:
        return [e for e in self._load().values() if e["status"] == PENDING]
