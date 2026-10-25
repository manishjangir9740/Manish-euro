"""Audit trail logging for store operations.

Tracks who did what, when, with what reason code and reference.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from pos.config import AUDIT_LOG_FILE
from pos.domain.filelock import file_lock, read_json, write_json_atomic


class AuditLogger:
    """Records security and compliance events for financial and managerial audits."""

    def __init__(self, log_file: Optional[Path] = None):
        self.file_path = Path(log_file or AUDIT_LOG_FILE)
        self.events: List[Dict[str, Any]] = []
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        self.events = read_json(self.file_path, [])

    def _save(self) -> None:
        write_json_atomic(self.file_path, self.events)

    def log(
        self,
        who: str,
        what: str,
        reason_code: Optional[str] = None,
        ref: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an immutable audit entry."""
        with file_lock(self.file_path):
            self._append(who, what, reason_code, ref, details)

    def _append(self, who, what, reason_code, ref, details) -> None:
        self._ensure_loaded()
        now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        entry = {
            "timestamp": now_iso,
            "who": who,
            "what": what,
            "reason_code": reason_code,
            "ref": ref,
            "details": details or {},
        }
        self.events.append(entry)
        self._save()
