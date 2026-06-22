"""
================================================================================
File:          automation_queue.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 14:40 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 14:40 EST

Purpose:
    Manages the auto-queue for Tier 2 / Tier 3: items that were classified as
    AUTO_QUEUED / AUTO_EXECUTE wait out a CANCEL window before they may fire.
    Provides cancel, expire-to-ready, and a full audit trail of every automated
    decision (timestamp, score, state, reason, account, outcome) per the brief.

    This module does NOT submit orders itself -- it decides WHEN an item is
    eligible to fire. The caller performs the actual (gated) send.

Change Log:
    2026-06-13 14:40 EST  v1.0.0  Initial implementation (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

UTC = timezone.utc


@dataclass
class QueueItem:
    item_id: str
    signal_id: str
    proposal_id: str
    account_id: str
    symbol: str
    score: float
    state: str                  # AUTO_QUEUED | AUTO_EXECUTE | CANCELLED | FIRED | EXPIRED
    queued_at: datetime
    cancel_deadline: datetime
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "signal_id": self.signal_id,
            "proposal_id": self.proposal_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "score": round(self.score, 2),
            "state": self.state,
            "queued_at": self.queued_at.isoformat(),
            "cancel_deadline": self.cancel_deadline.isoformat(),
            "reason": self.reason,
        }


class AutomationAudit:
    """Append-only JSONL audit trail of automated decisions."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = Lock()

    def record(self, event: dict) -> None:
        payload = {"ts": datetime.now(UTC).isoformat(), **event}
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\n")


class AutomationQueue:
    """Thread-safe queue of items awaiting their cancel window."""

    def __init__(self, audit: AutomationAudit | None = None) -> None:
        self._items: dict[str, QueueItem] = {}
        self._lock = Lock()
        self._audit = audit

    def enqueue(self, item: QueueItem) -> QueueItem:
        with self._lock:
            self._items[item.item_id] = item
        if self._audit:
            self._audit.record({"action": "enqueue", **item.as_dict()})
        return item

    def cancel(self, item_id: str, *, reason: str = "operator_cancel") -> Optional[QueueItem]:
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item.state not in ("AUTO_QUEUED", "AUTO_EXECUTE"):
                return None
            item.state = "CANCELLED"
            item.reason = reason
        if self._audit:
            self._audit.record({"action": "cancel", **item.as_dict()})
        return item

    def ready_to_fire(self, now: datetime | None = None) -> list[QueueItem]:
        """Items whose cancel window has elapsed and are still pending."""

        now = now or datetime.now(UTC)
        with self._lock:
            return [
                item
                for item in self._items.values()
                if item.state in ("AUTO_QUEUED", "AUTO_EXECUTE")
                and now >= item.cancel_deadline
            ]

    def mark_fired(self, item_id: str, *, outcome: str) -> Optional[QueueItem]:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return None
            item.state = "FIRED"
            item.reason = outcome
        if self._audit:
            self._audit.record({"action": "fire", "outcome": outcome, **item.as_dict()})
        return item

    def pending(self) -> list[QueueItem]:
        with self._lock:
            return [i for i in self._items.values() if i.state in ("AUTO_QUEUED", "AUTO_EXECUTE")]

    def get(self, item_id: str) -> Optional[QueueItem]:
        with self._lock:
            return self._items.get(item_id)
