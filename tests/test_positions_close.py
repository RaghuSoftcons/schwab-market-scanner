"""
File: test_positions_close.py
Created: 2026-06-22 15:20 EST
Author: Claude (Anthropic) + Raghu
Version: 2.0.0
Last Modified: 2026-06-22 16:55 EST

Change Log:
- 2026-06-22 15:20 EST | 1.0.0 | Authoritative Schwab-pull open positions + MARKET close.
- 2026-06-22 16:55 EST | 2.0.0 | Switched to DASHBOARD-TRACKED positions (only live sends from
  this dashboard this session are eligible for Close-now), per Raghu. Tests the in-memory tracker,
  MARKET close-leg inversion, and triple-lock/confirm gating with a stub client (no live calls).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import market_scanner.app as app
from market_scanner.app import (
    _close_position_response,
    _market_close_legs,
    _register_active_position,
    _tracked_positions_response,
)
from market_scanner.models import ClosePositionRequest
from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg


def _proposal(symbol="SMCI", direction="long", action="BUY"):
    leg = OptionProposalLeg(
        action=action, qty=2, symbol=symbol, expiry=date(2026, 6, 26), strike=45, right="CALL", price=2.5
    )
    leg = leg.model_copy(update={"broker_symbol": "SMCI  260626C00045000"})
    return OptionProposal(
        id="p1", signal_id="s1", symbol=symbol, direction=direction, structure="single",
        created_at=datetime.now(timezone.utc), expiry=date(2026, 6, 26), quantity=2,
        legs=[leg], debit=500, max_loss=500,
    )


def _accounts():
    return {
        "66502618": SimpleNamespace(id="66502618", account_hash="HASH1", enabled=True),
        "47169783": SimpleNamespace(id="47169783", account_hash="HASH2", enabled=True),
    }


def _reset():
    app.active_positions.clear()


def test_register_and_list_tracked_position() -> None:
    _reset()
    accts = _accounts()
    _register_active_position(_proposal(), ["66502618", "47169783"], accts, {"66502618": "OID1", "47169783": "OID2"})
    resp = _tracked_positions_response()
    assert len(resp.positions) == 1
    pos = resp.positions[0]
    assert pos.symbol == "SMCI"
    assert pos.account_count == 2
    assert pos.legs[0].broker_symbol == "SMCI  260626C00045000"
    assert "this session" in resp.note
    _reset()


def test_market_close_legs_inverts_action() -> None:
    long_legs = [{"action": "BUY", "qty": 2, "broker_symbol": "SMCI  260626C00045000"}]
    assert _market_close_legs(long_legs)[0]["instruction"] == "SELL_TO_CLOSE"
    short_legs = [{"action": "SELL", "qty": 1, "broker_symbol": "SMCI  260626P00045000"}]
    assert _market_close_legs(short_legs)[0]["instruction"] == "BUY_TO_CLOSE"


class _StubClient:
    def __init__(self):
        self.placed = []

    def place_order(self, account_hash, payload):
        self.placed.append((account_hash, payload))
        return {"broker_order_id": "NEW1"}

    def cancel_order(self, account_hash, order_id):
        pass


def test_close_unknown_symbol_is_blocked() -> None:
    _reset()
    resp = _close_position_response(symbol="NVDA", request=ClosePositionRequest(confirm_live_order=True), order_client=_StubClient())
    assert resp.status == "blocked"
    assert any("No dashboard-tracked position" in n for n in resp.notes)


def test_close_blocked_when_live_gate_closed() -> None:
    # Dry-run config: triple-lock closed -> no MARKET order placed; payload returned for review.
    _reset()
    _register_active_position(_proposal(), ["66502618"], _accounts(), {"66502618": "OID1"})
    client = _StubClient()
    resp = _close_position_response(symbol="SMCI", request=ClosePositionRequest(confirm_live_order=True), order_client=client)
    assert resp.status in {"blocked", "dry_run"}
    assert client.placed == []  # nothing sent live
    assert resp.account_results[0].order_payload["orderType"] == "MARKET"
    # Position stays tracked since it was not actually closed.
    assert "SMCI" in app.active_positions
    _reset()


def test_close_submits_and_clears_when_gate_open(monkeypatch) -> None:
    # Force the live gate open to exercise the live close path against the stub (no real Schwab).
    _reset()
    _register_active_position(_proposal(), ["66502618", "47169783"], _accounts(), {"66502618": "OID1", "47169783": "OID2"})
    monkeypatch.setattr(app.settings.service, "execution_mode", "live", raising=False)
    monkeypatch.setattr(app.settings.service, "allow_live_orders", True, raising=False)
    monkeypatch.setattr(app.settings.service, "trading_enabled", True, raising=False)
    assert app.settings.service.live_gate_open is True
    client = _StubClient()
    resp = _close_position_response(symbol="SMCI", request=ClosePositionRequest(confirm_live_order=True), order_client=client)
    assert resp.status == "submitted"
    assert len(client.placed) == 2  # one MARKET close per tracked account
    assert all(p["orderType"] == "MARKET" for _, p in client.placed)
    # Fully closed -> removed from tracker.
    assert "SMCI" not in app.active_positions
    _reset()
