"""Persistent operator dashboard settings."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


MAX_LOSS_CHOICES = (200, 300, 400, 500)
DEFAULT_MAX_LOSS = 300
ENTRY_OFFSET_CENT_CHOICES = (0, 5, 10, 20, 30, 40, 50)
DEFAULT_ENTRY_OFFSET_CENTS = 0  # 0c = a pure limit order at the natural price (no marketable offset)
EXPIRY_CHOICES = ("0DTE", "1DTE", "2DTE", "3DTE", "THIS_FRIDAY", "NEXT_WEEK_FRIDAY")
DEFAULT_EXPIRY_LABEL = "1DTE"
DEFAULT_TARGET_PERCENTAGES = (20.0, 40.0, 50.0)
MAX_TARGET_PERCENT_COUNT = 3
STOP_LOSS_PERCENT_CHOICES = (0, 20, 25, 30, 40, 50, 60, 70, 80)
DEFAULT_STOP_LOSS_PERCENT = 50
DEFAULT_ALLOW_ITM = False
DEFAULT_CLOSE_ON_REVERSAL = True
# OTOCO ("1st Triggers OCO") bracketed entry. When on, single-leg entries are placed as N
# bracketed slices (one TRIGGER entry per exit target, each triggering an OCO[target, stop]),
# so exits are attached at Schwab on fill. Ships ON.
DEFAULT_OTOCO = True
# Active stop management (single-leg). Default "fixed" = today's behavior. Held as one dict.
STOP_MODE_CHOICES = ("fixed", "breakeven", "trailing", "be_then_trail")
DEFAULT_STOP_MGMT = {
    "stop_mode": "be_then_trail",
    "trail_start_percent": 10,
    "trail_distance_percent": 8,
    "trail_poll_seconds": 4,
}


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
        self._stop_loss_percent = loaded["stop_loss_percent"]
        self._allow_itm = loaded["allow_itm"]
        self._close_on_reversal = loaded["close_on_reversal"]
        self._otoco = loaded["otoco"]
        self._stop_mgmt = loaded["stop_mgmt"]

    @property
    def stop_mode_choices(self) -> list[str]:
        return list(STOP_MODE_CHOICES)

    @property
    def max_loss_choices(self) -> list[int]:
        return list(MAX_LOSS_CHOICES)

    @property
    def entry_offset_choices(self) -> list[int]:
        return list(ENTRY_OFFSET_CENT_CHOICES)

    @property
    def expiry_choices(self) -> list[str]:
        return list(EXPIRY_CHOICES)

    @property
    def stop_loss_percent_choices(self) -> list[int]:
        return list(STOP_LOSS_PERCENT_CHOICES)

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

    def get_stop_loss_percent(self) -> int:
        with self._lock:
            return self._stop_loss_percent

    def get_allow_itm(self) -> bool:
        with self._lock:
            return self._allow_itm

    def get_close_on_reversal(self) -> bool:
        with self._lock:
            return self._close_on_reversal

    def get_otoco(self) -> bool:
        with self._lock:
            return self._otoco

    def get_stop_mgmt(self) -> dict:
        with self._lock:
            return dict(self._stop_mgmt)

    def get_stop_mode(self) -> str:
        with self._lock:
            return self._stop_mgmt["stop_mode"]

    def set_stop_mgmt(self, partial: object) -> dict:
        merged = self._normalize_stop_mgmt(partial, base=self._stop_mgmt)
        with self._lock:
            self._stop_mgmt = merged
            self._save()
            return dict(merged)

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

    def set_stop_loss_percent(self, value: int) -> int:
        selected = self._normalize_stop_loss_percent(value)
        with self._lock:
            self._stop_loss_percent = selected
            self._save()
            return selected

    def set_allow_itm(self, value: object) -> bool:
        selected = self._normalize_allow_itm(value)
        with self._lock:
            self._allow_itm = selected
            self._save()
            return selected

    def set_close_on_reversal(self, value: object) -> bool:
        selected = self._normalize_close_on_reversal(value)
        with self._lock:
            self._close_on_reversal = selected
            self._save()
            return selected

    def set_otoco(self, value: object) -> bool:
        selected = self._normalize_otoco(value)
        with self._lock:
            self._otoco = selected
            self._save()
            return selected

    def _load(self) -> dict[str, bool | int | str | list[float]]:
        if self.path is None or not self.path.exists():
            return {
                "allow_itm": DEFAULT_ALLOW_ITM,
                "close_on_reversal": DEFAULT_CLOSE_ON_REVERSAL,
                "otoco": DEFAULT_OTOCO,
                "expiry_label": DEFAULT_EXPIRY_LABEL,
                "max_loss_dollars": DEFAULT_MAX_LOSS,
                "entry_offset_cents": DEFAULT_ENTRY_OFFSET_CENTS,
                "target_percentages": list(DEFAULT_TARGET_PERCENTAGES),
                "stop_loss_percent": DEFAULT_STOP_LOSS_PERCENT,
                "stop_mgmt": dict(DEFAULT_STOP_MGMT),
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "allow_itm": DEFAULT_ALLOW_ITM,
                "close_on_reversal": DEFAULT_CLOSE_ON_REVERSAL,
                "otoco": DEFAULT_OTOCO,
                "expiry_label": DEFAULT_EXPIRY_LABEL,
                "max_loss_dollars": DEFAULT_MAX_LOSS,
                "entry_offset_cents": DEFAULT_ENTRY_OFFSET_CENTS,
                "target_percentages": list(DEFAULT_TARGET_PERCENTAGES),
                "stop_loss_percent": DEFAULT_STOP_LOSS_PERCENT,
                "stop_mgmt": dict(DEFAULT_STOP_MGMT),
            }
        max_loss = payload.get("max_loss_dollars") if isinstance(payload, dict) else None
        entry_offset = payload.get("entry_offset_cents") if isinstance(payload, dict) else None
        expiry_label = payload.get("expiry_label") if isinstance(payload, dict) else None
        target_percentages = payload.get("target_percentages") if isinstance(payload, dict) else None
        stop_loss_percent = payload.get("stop_loss_percent") if isinstance(payload, dict) else None
        allow_itm = payload.get("allow_itm") if isinstance(payload, dict) else None
        close_on_reversal = payload.get("close_on_reversal") if isinstance(payload, dict) else None
        otoco = payload.get("otoco") if isinstance(payload, dict) else None
        stop_mgmt = payload.get("stop_mgmt") if isinstance(payload, dict) else None
        return {
            "allow_itm": self._normalize_allow_itm(allow_itm),
            "close_on_reversal": self._normalize_close_on_reversal(close_on_reversal),
            "otoco": self._normalize_otoco(otoco),
            "expiry_label": self._normalize_expiry_label(expiry_label),
            "max_loss_dollars": self._normalize_max_loss(max_loss),
            "entry_offset_cents": self._normalize_entry_offset(entry_offset),
            "target_percentages": self.normalize_target_percentages(target_percentages, strict=False),
            # SAFETY: always start at 50% SL on bridge startup — never carry over a persisted "No SL"
            # (0) or other value. Operator can still change it during a session; it resets next restart.
            "stop_loss_percent": DEFAULT_STOP_LOSS_PERCENT,
            "stop_mgmt": self._normalize_stop_mgmt(stop_mgmt),
        }

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "allow_itm": self._allow_itm,
            "close_on_reversal": self._close_on_reversal,
            "otoco": self._otoco,
            "entry_offset_cents": self._entry_offset_cents,
            "expiry_label": self._expiry_label,
            "max_loss_dollars": self._max_loss_dollars,
            "stop_loss_percent": self._stop_loss_percent,
            "target_percentages": self._target_percentages,
            "stop_mgmt": self._stop_mgmt,
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _normalize_stop_mgmt(value: object, base: dict | None = None) -> dict:
        out = dict(base) if base else dict(DEFAULT_STOP_MGMT)
        src = value if isinstance(value, dict) else {}
        mode = str(src.get("stop_mode", out["stop_mode"]) or "").strip().lower()
        out["stop_mode"] = mode if mode in STOP_MODE_CHOICES else out["stop_mode"]
        for key, lo, hi in (
            ("trail_start_percent", 0, 100),
            ("trail_distance_percent", 0, 100),
            ("trail_poll_seconds", 1, 60),
        ):
            if key in src:
                try:
                    out[key] = min(max(int(src[key]), lo), hi)
                except (TypeError, ValueError):
                    pass
        return out

    @staticmethod
    def _normalize_max_loss(value: object) -> int:
        try:
            selected = int(value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_LOSS
        return selected if selected in MAX_LOSS_CHOICES else DEFAULT_MAX_LOSS

    @staticmethod
    def _normalize_entry_offset(value: object) -> int:
        try:
            selected = int(value)
        except (TypeError, ValueError):
            return DEFAULT_ENTRY_OFFSET_CENTS
        return selected if selected in ENTRY_OFFSET_CENT_CHOICES else DEFAULT_ENTRY_OFFSET_CENTS

    @staticmethod
    def _normalize_stop_loss_percent(value: object) -> int:
        try:
            selected = int(value)
        except (TypeError, ValueError):
            return DEFAULT_STOP_LOSS_PERCENT
        return selected if selected in STOP_LOSS_PERCENT_CHOICES else DEFAULT_STOP_LOSS_PERCENT

    @staticmethod
    def _normalize_expiry_label(value: object) -> str:
        selected = str(value or "").upper().strip().replace(" ", "_")
        return selected if selected in EXPIRY_CHOICES else DEFAULT_EXPIRY_LABEL

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
    def _normalize_close_on_reversal(value: object) -> bool:
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
        return DEFAULT_CLOSE_ON_REVERSAL

    @staticmethod
    def _normalize_otoco(value: object) -> bool:
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
        return DEFAULT_OTOCO

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
