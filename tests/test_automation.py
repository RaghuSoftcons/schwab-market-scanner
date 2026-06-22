"""
================================================================================
File:          test_automation.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 14:40 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 14:40 EST

Purpose:
    Tests the tier classification engine and the cancel-window queue, including
    the critical invariant that Tier OFF/1 never auto-queues or auto-executes
    (so the bridge behaves identically to the original by default).

Change Log:
    2026-06-13 14:40 EST  v1.0.0  Initial tests (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nt_schwab_bridge.automation import (
    ActionState,
    AutomationConfig,
    AutomationEngine,
    Tier,
)
from nt_schwab_bridge.automation_queue import AutomationQueue, QueueItem

UTC = timezone.utc
NOW = datetime(2026, 6, 12, 11, 0, 0, tzinfo=UTC)


def _engine(tier, **kw):
    cfg = AutomationConfig(tier=tier)
    for k, v in kw.items():
        setattr(cfg, k, v)
    return AutomationEngine(cfg)


def test_tier_parse():
    assert Tier.parse("off") == Tier.OFF
    assert Tier.parse("1") == Tier.TIER1
    assert Tier.parse("autopilot") == Tier.TIER3
    assert Tier.parse(None) == Tier.TIER1
    assert Tier.parse("garbage") == Tier.TIER1


def test_tier_off_always_manual():
    eng = _engine(Tier.OFF)
    out = eng.classify(95, account_id="a", now=NOW)
    assert out.state == ActionState.READY_MANUAL
    assert out.cancel_deadline is None


def test_tier1_filters_low_score():
    eng = _engine(Tier.TIER1, smart_assist_min_score=50)
    assert eng.classify(40, account_id="a", now=NOW).state == ActionState.FILTERED
    assert eng.classify(70, account_id="a", now=NOW).state == ActionState.READY_MANUAL


def test_tier1_never_auto_queues():
    eng = _engine(Tier.TIER1)
    out = eng.classify(99, account_id="a", now=NOW)
    assert out.state == ActionState.READY_MANUAL  # high score still manual on Tier 1


def test_tier2_bands():
    eng = _engine(Tier.TIER2, manual_review_min_score=60, auto_queue_min_score=80)
    assert eng.classify(55, account_id="a", now=NOW).state == ActionState.AUTO_REJECTED
    assert eng.classify(70, account_id="a", now=NOW).state == ActionState.MANUAL_REVIEW
    high = eng.classify(85, account_id="a", now=NOW)
    assert high.state == ActionState.AUTO_QUEUED
    assert high.cancel_deadline == NOW + timedelta(seconds=10)


def test_tier3_requires_account_toggle():
    eng = _engine(Tier.TIER3, per_account_auto={"on": True})
    # account not enabled -> manual review even at high score
    assert eng.classify(90, account_id="off", now=NOW).state == ActionState.MANUAL_REVIEW
    # account enabled -> auto execute
    out = eng.classify(90, account_id="on", now=NOW)
    assert out.state == ActionState.AUTO_EXECUTE
    assert out.cancel_deadline == NOW + timedelta(seconds=10)


def test_tier3_low_score_still_rejected():
    eng = _engine(Tier.TIER3, per_account_auto={"on": True})
    assert eng.classify(50, account_id="on", now=NOW).state == ActionState.AUTO_REJECTED


def _item(state="AUTO_QUEUED", deadline=NOW + timedelta(seconds=10)):
    return QueueItem(
        item_id="i1", signal_id="s1", proposal_id="p1", account_id="a",
        symbol="QQQ", score=85, state=state, queued_at=NOW, cancel_deadline=deadline,
    )


def test_queue_cancel_prevents_fire():
    q = AutomationQueue()
    q.enqueue(_item())
    cancelled = q.cancel("i1")
    assert cancelled.state == "CANCELLED"
    # After the deadline, a cancelled item must NOT be ready to fire.
    ready = q.ready_to_fire(now=NOW + timedelta(seconds=30))
    assert ready == []


def test_queue_fires_after_window():
    q = AutomationQueue()
    q.enqueue(_item())
    # Before the deadline -> not ready.
    assert q.ready_to_fire(now=NOW + timedelta(seconds=5)) == []
    # After the deadline -> ready.
    ready = q.ready_to_fire(now=NOW + timedelta(seconds=11))
    assert len(ready) == 1
    fired = q.mark_fired("i1", outcome="submitted")
    assert fired.state == "FIRED"
    assert q.ready_to_fire(now=NOW + timedelta(seconds=20)) == []


def test_audit_records_written(tmp_path):
    from nt_schwab_bridge.automation_queue import AutomationAudit

    audit = AutomationAudit(tmp_path / "audit.jsonl")
    q = AutomationQueue(audit=audit)
    q.enqueue(_item())
    q.cancel("i1")
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # enqueue + cancel
