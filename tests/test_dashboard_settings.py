# ============================================================================
# File:          test_dashboard_settings.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
# Purpose:       Phase 1 of the look&feel parity port — durable dashboard settings
#                backend (SL %, OTOCO, targets, entry offset, stop-management)
#                exposed via GET/POST /dashboard/settings.
# ============================================================================
from fastapi.testclient import TestClient

import market_scanner.app as m

_DEFAULTS = {"stop_loss_percent": 50, "otoco": True, "entry_offset_cents": 0,
             "target_percentages": [20, 40, 50], "stop_mode": "be_then_trail"}


def _reset(c):
    c.post("/dashboard/settings", json=_DEFAULTS)


def test_settings_get_shape():
    c = TestClient(m.app)
    _reset(c)
    g = c.get("/dashboard/settings").json()
    for k in ("max_loss_dollars", "max_loss_choices", "entry_offset_cents", "entry_offset_choices",
              "expiry_label", "expiry_choices", "target_percentages", "stop_loss_percent",
              "stop_loss_percent_choices", "allow_itm", "close_on_reversal", "otoco",
              "stop_mode", "stop_mode_choices", "trail_start_percent", "trail_distance_percent",
              "trail_poll_seconds"):
        assert k in g, f"missing settings key: {k}"
    # parity defaults with the Unified dashboard
    assert g["stop_loss_percent"] == 50
    assert g["entry_offset_cents"] == 0
    assert g["otoco"] is True
    assert 0 in g["stop_loss_percent_choices"] and 80 in g["stop_loss_percent_choices"]
    assert 0 in g["entry_offset_choices"]


def test_settings_post_roundtrip():
    c = TestClient(m.app)
    try:
        p = c.post("/dashboard/settings", json={
            "stop_loss_percent": 30, "otoco": False, "entry_offset_cents": 10,
            "target_percentages": [25, 50, 75], "stop_mode": "trailing", "trail_start_percent": 12,
        }).json()
        assert p["stop_loss_percent"] == 30
        assert p["otoco"] is False
        assert p["entry_offset_cents"] == 10
        assert p["target_percentages"] == [25.0, 50.0, 75.0]
        assert p["stop_mode"] == "trailing"
        assert p["trail_start_percent"] == 12
        # a fresh GET reflects the persisted values
        assert c.get("/dashboard/settings").json()["stop_loss_percent"] == 30
    finally:
        _reset(c)


def test_settings_rejects_bad_value():
    c = TestClient(m.app)
    try:
        r = c.post("/dashboard/settings", json={"target_percentages": ["not-a-number"]})
        assert r.status_code == 422
    finally:
        _reset(c)
