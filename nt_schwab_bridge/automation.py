"""
================================================================================
File:          automation.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 14:40 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 14:40 EST

Purpose:
    Automation tiers for the NT-Schwab Bridge (brief Step 4), layered on top of
    the existing dry-run send flow WITHOUT changing it when disabled. The engine
    classifies each proposal into an action state based on its score and the
    active tier:

      Tier OFF / 1 (Smart Assist): manual send. Low-score proposals are filtered
        out; the operator still clicks send. (Default -> identical to original.)
      Tier 2 (Auto-Send w/ Cancel Window): high-score auto-queues with a 10s
        CANCEL countdown; medium-score -> manual review; low-score -> auto-reject.
      Tier 3 (Full Autopilot): high-score auto-executes (still gated by the
        shared RiskManager + the bridge's existing live-order gates); per-account
        auto toggle; everything else falls back to manual review / auto-reject.

    SAFETY: the engine never bypasses the RiskManager or the bridge's live-order
    confirmation gates. A queued/auto item must ALSO pass risk evaluation before
    any order is sent. Default tier is 1, so with no config the bridge behaves
    exactly as it does today.

Change Log:
    2026-06-13 14:40 EST  v1.0.0  Initial implementation (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

UTC = timezone.utc


class Tier(str, Enum):
    OFF = "off"
    TIER1 = "1"
    TIER2 = "2"
    TIER3 = "3"

    @classmethod
    def parse(cls, value: str | None) -> "Tier":
        v = str(value or "1").strip().lower()
        mapping = {
            "off": cls.OFF,
            "0": cls.OFF,
            "1": cls.TIER1,
            "tier1": cls.TIER1,
            "smart_assist": cls.TIER1,
            "2": cls.TIER2,
            "tier2": cls.TIER2,
            "3": cls.TIER3,
            "tier3": cls.TIER3,
            "autopilot": cls.TIER3,
        }
        return mapping.get(v, cls.TIER1)


class ActionState(str, Enum):
    READY_MANUAL = "READY_MANUAL"      # operator must click send (Tier 1/off)
    FILTERED = "FILTERED"              # below smart-assist threshold; hidden
    AUTO_QUEUED = "AUTO_QUEUED"        # queued with cancel window (Tier 2/3)
    MANUAL_REVIEW = "MANUAL_REVIEW"    # medium score; needs operator
    AUTO_REJECTED = "AUTO_REJECTED"    # below review threshold; logged + dropped
    AUTO_EXECUTE = "AUTO_EXECUTE"      # Tier 3 high score; auto-send after gates


@dataclass
class AutomationConfig:
    tier: Tier = Tier.TIER1
    smart_assist_min_score: float = 50.0   # Tier 1: hide below this
    auto_queue_min_score: float = 80.0     # high score threshold
    manual_review_min_score: float = 60.0  # medium/low boundary
    cancel_window_seconds: int = 10
    # Per-account auto toggle for Tier 3 (account_id -> bool). Missing = False.
    per_account_auto: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "AutomationConfig":
        cfg = cls(tier=Tier.parse(os.environ.get("NT_AUTOMATION_TIER")))
        cfg.smart_assist_min_score = float(
            os.environ.get("NT_SMART_ASSIST_MIN_SCORE", cfg.smart_assist_min_score)
        )
        cfg.auto_queue_min_score = float(
            os.environ.get("NT_AUTO_QUEUE_MIN_SCORE", cfg.auto_queue_min_score)
        )
        cfg.manual_review_min_score = float(
            os.environ.get("NT_MANUAL_REVIEW_MIN_SCORE", cfg.manual_review_min_score)
        )
        cfg.cancel_window_seconds = int(
            os.environ.get("NT_CANCEL_WINDOW_SECONDS", cfg.cancel_window_seconds)
        )
        return cfg


@dataclass
class TierOutcome:
    state: ActionState
    reason: str
    score: float
    cancel_deadline: Optional[datetime] = None  # set for AUTO_QUEUED / AUTO_EXECUTE

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "reason": self.reason,
            "score": round(self.score, 2),
            "cancel_deadline": self.cancel_deadline.isoformat() if self.cancel_deadline else None,
        }


class AutomationEngine:
    """Pure classification of a proposal into an action state for the active tier."""

    def __init__(self, config: AutomationConfig) -> None:
        self._config = config

    @property
    def tier(self) -> Tier:
        return self._config.tier

    def classify(
        self,
        score: float,
        *,
        account_id: str,
        now: datetime | None = None,
    ) -> TierOutcome:
        cfg = self._config
        now = now or datetime.now(UTC)

        # Tier OFF / Tier 1: manual send, with low-score filtering on Tier 1.
        if cfg.tier in (Tier.OFF, Tier.TIER1):
            if cfg.tier == Tier.TIER1 and score < cfg.smart_assist_min_score:
                return TierOutcome(
                    ActionState.FILTERED,
                    f"score {score:.0f} < smart-assist min {cfg.smart_assist_min_score:.0f}",
                    score,
                )
            return TierOutcome(ActionState.READY_MANUAL, "manual send (operator clicks)", score)

        # Tier 2 / Tier 3 thresholds.
        if score < cfg.manual_review_min_score:
            return TierOutcome(
                ActionState.AUTO_REJECTED,
                f"score {score:.0f} < review min {cfg.manual_review_min_score:.0f}",
                score,
            )
        if score < cfg.auto_queue_min_score:
            return TierOutcome(
                ActionState.MANUAL_REVIEW,
                f"score {score:.0f} in review band "
                f"[{cfg.manual_review_min_score:.0f}, {cfg.auto_queue_min_score:.0f})",
                score,
            )

        # High score.
        deadline = now + timedelta(seconds=cfg.cancel_window_seconds)
        if cfg.tier == Tier.TIER2:
            return TierOutcome(
                ActionState.AUTO_QUEUED,
                f"high score {score:.0f}; {cfg.cancel_window_seconds}s cancel window",
                score,
                cancel_deadline=deadline,
            )

        # Tier 3: auto-execute only if this account is toggled on; else manual.
        if not cfg.per_account_auto.get(account_id, False):
            return TierOutcome(
                ActionState.MANUAL_REVIEW,
                f"high score {score:.0f} but account {account_id} not auto-enabled",
                score,
            )
        return TierOutcome(
            ActionState.AUTO_EXECUTE,
            f"autopilot: high score {score:.0f}; {cfg.cancel_window_seconds}s cancel window",
            score,
            cancel_deadline=deadline,
        )
