"""Persistent operator dashboard settings."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


MAX_LOSS_CHOICES = (200, 300, 400, 500)
DEFAULT_MAX_LOSS = 300
ENTRY_OFFSET_CENT_CHOICES = (10, 20, 30, 40, 50)
DEFAULT_ENTRY_OFFSET_CENTS = 30
EXPIRY_CHOICES = ("0DTE", "1DTE", "2DTE", "3DTE", "THIS_FRIDAY", "NEXT_WEEK_FRIDAY")
DEFAULT_EXPIRY_LABEL = "1DTE"
DEFAULT_TARGET_PERCENTAGES = (20.0, 40.0, 50.0)
MAX_TARGET_PERCENT_COUNT = 3
DEFAULT_ALLOW_ITM = False
# 0 disables the protective stop (target-only exit). Otherwise the OCO stop is placed
# at entry_fill * (1 - stop_loss_percent/100). Ported from the Unified Platform for OCO exits.
STOP_LOSS_PERCENT_CHOICES = (0, 20, 25, 30, 40, 50, 60, 70, 80)
DEFAULT_STOP_LOSS_PERCENT = 50
# Close-on-Reversal (#9c): auto-close an open position when the opposite signal fires for the
# same symbol. Ships OFF for the re-scanning scanner until validated.
DEFAULT_CLOSE_ON_REVERSAL = False


class DashboardSettingsStore:
    """Persist proposal-planner settings chosen from the dashboard."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None
        self._lock = Lock()
        loaded = self._load()
        self._max_loss_dollars = loaded["max_loss_dollars"]
        self._entry_offset_cents = loaded["entry_offset_cents"]
        self._expiry_label = loaded["expiry_label"]
        self._target_percentages = loaded["target_percentages"]
        self._allow_itm = loaded["allow_itm"]
        self._stop_loss_percent = loaded["stop_loss_percent"]
        self._close_on_reversal = loaded["close_on_reversal"]

    @property
    def max_loss_choices(self) -> list[int]:
        return list(MAX_LOSS_CHOICES)

    @property
    def stop_loss_percent_choices(self) -> list[int]:
        return list(STOP_LOSS_PERCENT_CHOICES)

    @property
    def entry_offset_choices(self) -> list[int]:
        return list(ENTRY_OFFSET_CENT_CHOICES)

    @property
    def expiry_choices(self) -> list[str]:
        return list(EXPIRY_CHOICES)

    def get_max_loss_dollars(self) -> int:
        with self._lock:
            return self._max_loss_dollars

    def get_entry_offset_cents(self) -> int:
        with self._lock:
            return self._entry_offset_cents

    def get_expiry_label(self) -> str:
        with self._lock:
            return self._expiry_label

    def get_target_percentages(self) -> list[float]:
        with self._lock:
            return list(self._target_percentages)

    def get_allow_itm(self) -> bool:
        with self._lock:
            return self._allow_itm

    def get_stop_loss_percent(self) -> int:
        with self._lock:
            return self._stop_loss_percent

    def get_close_on_reversal(self) -> bool:
        with self._lock:
            return self._close_on_reversal

    def set_max_loss_dollars(self, value: int) -> int:
        selected = self._normalize_max_loss(value)
        with self._lock:
            self._max_loss_dollars = selected
            self._save()
            return selected

    def set_entry_offset_cents(self, value: int) -> int:
        selected = self._normalize_entry_offset(value)
        with self._lock:
            self._entry_offset_cents = selected
            self._save()
            return selected

    def set_expiry_label(self, value: str) -> str:
        selected = self._normalize_expiry_label(value)
        with self._lock:
            self._expiry_label = selected
            self._save()
            return selected

    def set_target_percentages(self, value: object) -> list[float]:
        selected = self.normalize_target_percentages(value, strict=True)
        with self._lock:
            self._target_percentages = selected
            self._save()
            return list(selected)

    def set_allow_itm(self, value: object) -> bool:
        selected = self._normalize_allow_itm(value)
        with self._lock:
            self._allow_itm = selected
            self._save()
            return selected

    def set_stop_loss_percent(self, value: int) -> int:
        selected = self._normalize_stop_loss_percent(value)
        with self._lock:
            self._stop_loss_percent = selected
            self._save()
            return selected

    def set_close_on_reversal(self, value: object) -> bool:
        selected = self._normalize_bool(value, DEFAULT_CLOSE_ON_REVERSAL)
        with self._lock:
            self._close_on_reversal = selected
            self._save()
            return selected

    def _load(self) -> dict[str, bool | int | str | list[float]]:
        if self.path is None or not self.path.exists():
            return {
                "allow_itm": DEFAULT_ALLOW_ITM,
                "expiry_label": DEFAULT_EXPIRY_LABEL,
                "max_loss_dollars": DEFAULT_MAX_LOSS,
                "entry_offset_cents": DEFAULT_ENTRY_OFFSET_CENTS,
                "target_percentages": list(DEFAULT_TARGET_PERCENTAGES),
                "stop_loss_percent": DEFAULT_STOP_LOSS_PERCENT,
                "close_on_reversal": DEFAULT_CLOSE_ON_REVERSAL,
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "allow_itm": DEFAULT_ALLOW_ITM,
                "expiry_label": DEFAULT_EXPIRY_LABEL,
                "max_loss_dollars": DEFAULT_MAX_LOSS,
                "entry_offset_cents": DEFAULT_ENTRY_OFFSET_CENTS,
                "target_percentages": list(DEFAULT_TARGET_PERCENTAGES),
                "stop_loss_percent": DEFAULT_STOP_LOSS_PERCENT,
                "close_on_reversal": DEFAULT_CLOSE_ON_REVERSAL,
            }
        max_loss = payload.get("max_loss_dollars") if isinstance(payload, dict) else None
        entry_offset = payload.get("entry_offset_cents") if isinstance(payload, dict) else None
        expiry_label = payload.get("expiry_label") if isinstance(payload, dict) else None
        target_percentages = payload.get("target_percentages") if isinstance(payload, dict) else None
        allow_itm = payload.get("allow_itm") if isinstance(payload, dict) else None
        stop_loss_percent = payload.get("stop_loss_percent") if isinstance(payload, dict) else None
        close_on_reversal = payload.get("close_on_reversal") if isinstance(payload, dict) else None
        return {
            "allow_itm": self._normalize_allow_itm(allow_itm),
            "expiry_label": self._normalize_expiry_label(expiry_label),
            "max_loss_dollars": self._normalize_max_loss(max_loss),
            "entry_offset_cents": self._normalize_entry_offset(entry_offset),
            "target_percentages": self.normalize_target_percentages(target_percentages, strict=False),
            "stop_loss_percent": self._normalize_stop_loss_percent(stop_loss_percent),
            "close_on_reversal": self._normalize_bool(close_on_reversal, DEFAULT_CLOSE_ON_REVERSAL),
        }

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "allow_itm": self._allow_itm,
            "entry_offset_cents": self._entry_offset_cents,
            "expiry_label": self._expiry_label,
            "max_loss_dollars": self._max_loss_dollars,
            "target_percentages": self._target_percentages,
            "stop_loss_percent": self._stop_loss_percent,
            "close_on_reversal": self._close_on_reversal,
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _normalize_max_loss(value: object) -> int:
        try:
            selected = int(value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_LOSS
        return selected if selected in MAX_LOSS_CHOICES else DEFAULT_MAX_LOSS

    @staticmethod
    def _normalize_stop_loss_percent(value: object) -> int:
        try:
            selected = int(value)
        except (TypeError, ValueError):
            return DEFAULT_STOP_LOSS_PERCENT
        return selected if selected in STOP_LOSS_PERCENT_CHOICES else DEFAULT_STOP_LOSS_PERCENT

    @staticmethod
    def _normalize_entry_offset(value: object) -> int:
        try:
            selected = int(value)
        except (TypeError, ValueError):
            return DEFAULT_ENTRY_OFFSET_CENTS
        return selected if selected in ENTRY_OFFSET_CENT_CHOICES else DEFAULT_ENTRY_OFFSET_CENTS

    @staticmethod
    def _normalize_expiry_label(value: object) -> str:
        selected = str(value or "").upper().strip().replace(" ", "_")
        return selected if selected in EXPIRY_CHOICES else DEFAULT_EXPIRY_LABEL

    @staticmethod
    def _normalize_bool(value: object, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, int):
            return bool(value)
        return default

    @staticmethod
    def _normalize_allow_itm(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, int):
            return bool(value)
        return DEFAULT_ALLOW_ITM

    @staticmethod
    def normalize_target_percentages(value: object, *, strict: bool) -> list[float]:
        if not isinstance(value, (list, tuple)):
            if strict:
                raise ValueError("target_percentages must be a list")
            return list(DEFAULT_TARGET_PERCENTAGES)
        targets: list[float] = []
        for item in value:
            try:
                target = float(item)
            except (TypeError, ValueError):
                if strict:
                    raise ValueError("target_percentages must contain numbers") from None
                return list(DEFAULT_TARGET_PERCENTAGES)
            if target <= 0 or target > 1000:
                if strict:
                    raise ValueError("target_percentages must be between 0 and 1000")
                return list(DEFAULT_TARGET_PERCENTAGES)
            targets.append(round(target, 4))
        if not 1 <= len(targets) <= MAX_TARGET_PERCENT_COUNT:
            if strict:
                raise ValueError(f"target_percentages must contain 1 to {MAX_TARGET_PERCENT_COUNT} values")
            return list(DEFAULT_TARGET_PERCENTAGES)
        return targets
