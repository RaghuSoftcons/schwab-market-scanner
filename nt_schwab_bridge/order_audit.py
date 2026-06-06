"""Persistent local audit trail for dashboard order send attempts."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


class OrderAuditStore:
    """Append-only JSONL store for local order notes and send metadata."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None
        self._lock = Lock()

    def append(self, event: dict[str, Any]) -> None:
        if self.path is None:
            return
        payload = json.dumps(event, sort_keys=True, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")

    def list_events(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events
