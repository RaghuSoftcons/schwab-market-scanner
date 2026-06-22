"""
File: test_automation_routes.py
Created: 2026-06-22 15:10 EST
Author: Claude (Anthropic) + Raghu
Version: 1.0.0
Last Modified: 2026-06-22 15:10 EST

Change Log:
- 2026-06-22 15:10 EST | 1.0.0 | Scanner automation-tier endpoints (#7): status, tier switch
  with Tier 2/3 confirm gate, per-account toggle, kill switch. The triple-lock stays the final gate.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from market_scanner.app import app, automation_config, kill_switch
from nt_schwab_bridge.automation import Tier


def _reset() -> None:
    automation_config.tier = Tier.TIER1
    automation_config.per_account_auto.clear()
    kill_switch["engaged"] = False
    kill_switch["reason"] = ""


def test_status_reports_tier_and_lock() -> None:
    _reset()
    body = TestClient(app).get("/automation/status").json()
    assert body["tier"] == "1"
    assert "live_gate_open" in body  # triple-lock visibility
    assert body["kill_switch"]["engaged"] is False


def test_tier2_requires_confirm() -> None:
    _reset()
    client = TestClient(app)
    blocked = client.post("/automation/tier", json={"tier": "2"})
    assert blocked.status_code == 409
    ok = client.post("/automation/tier", json={"tier": "2", "confirm": True})
    assert ok.status_code == 200
    assert ok.json()["tier"] == "2"
    _reset()


def test_account_toggle_and_kill_switch_drops_to_tier1() -> None:
    _reset()
    client = TestClient(app)
    client.post("/automation/tier", json={"tier": "3", "confirm": True})
    client.post("/automation/account-toggle", json={"account_id": "66502618", "enabled": True})
    assert automation_config.per_account_auto["66502618"] is True
    killed = client.post("/automation/kill", json={"reason": "test"}).json()
    assert killed["kill_switch"]["engaged"] is True
    assert killed["tier"] == "1"  # kill drops autopilot to manual
    released = client.post("/automation/kill/release").json()
    assert released["kill_switch"]["engaged"] is False
    _reset()


def test_pnl_summary_endpoint_shape() -> None:
    body = TestClient(app).get("/pnl/summary").json()
    assert "pnl" in body
    assert "pnl_by_account" in body
