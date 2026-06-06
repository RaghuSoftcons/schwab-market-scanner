"""Persistent dashboard account-selection state."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


class AccountSelectionStore:
    """Persist the last selected Schwab account aliases for proposal routing."""

    def __init__(self, path: str | Path | None, default_selected_ids: list[str] | None = None) -> None:
        self.path = Path(path) if path else None
        self.default_selected_ids = list(dict.fromkeys(default_selected_ids or []))
        self._lock = Lock()
        self._has_saved_selection = False
        self._selected_account_ids = self._load()

    def get(self) -> list[str]:
        with self._lock:
            return list(self._selected_account_ids)

    def has_saved_selection(self) -> bool:
        with self._lock:
            return self._has_saved_selection

    def set(self, account_ids: list[str]) -> list[str]:
        selected = list(dict.fromkeys(account_id for account_id in account_ids if account_id))
        with self._lock:
            self._selected_account_ids = selected
            self._has_saved_selection = True
            self._save(selected)
            return list(selected)

    def _load(self) -> list[str]:
        if self.path is None or not self.path.exists():
            return list(self.default_selected_ids)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return list(self.default_selected_ids)
        selected = payload.get("selected_account_ids") if isinstance(payload, dict) else None
        if not isinstance(selected, list):
            return list(self.default_selected_ids)
        self._has_saved_selection = True
        return list(dict.fromkeys(str(item).strip() for item in selected if str(item).strip()))

    def _save(self, account_ids: list[str]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"selected_account_ids": account_ids}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
