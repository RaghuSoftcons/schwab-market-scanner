"""
File: test_positions_close.py
Created: 2026-06-22 15:20 EST
Author: Claude (Anthropic) + Raghu
Version: 3.0.0
Last Modified: 2026-06-22 17:55 EST

Change Log:
- 1.0.0 Authoritative pull. 2.0.0 Dashboard-tracked only.
- 3.0.0 Unified table model (PositionRow): Tracked/All modes + contract-close. Tests row mapping,
  spread detection, tracked enrichment, and triple-lock/confirm gating with stubs (no live calls).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import market_scanner.app as app
from market_scanner.app import (
    _close_contract_response,
    _register_active_position,
    _row_from_raw,
    _tracked_positions_response,
)
from market_scanner.models import CloseContractRequest
from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg


def _proposal(symbol="SMCI", direction="long", action="BUY"):
    leg = OptionProposalLeg(action=action, qty=2, symbol=symbol, expiry=date(2026, 6, 26), strike=45, right="CALL", price=2.5)
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


def test_row_from_raw_long_call() -> None:
    raw = {
        "instrument": {"symbol": "BRKB  260918C00490000", "assetType": "OPTION", "underlyingSymbol": "BRKB"},
        "longQuantity": 1, "shortQuantity": 0, "averagePrice": 22.88,
        "marketValue": 2073.0, "longOpenProfitLoss": -215.91,
    }
    row = _row_from_raw("66502618", raw, is_spread=False)
    assert row.qty == 1
    assert row.avg == 22.88
    assert row.mark == 20.73  # 2073 / (1 * 100)
    assert row.unrealized_pnl == -215.91
    assert row.closeable is True and row.is_spread is False


def test_row_from_raw_short_marks_positive() -> None:
    raw = {
        "instrument": {"symbol": "BRKB  260918C00495000", "assetType": "OPTION"},
        "longQuantity": 0, "shortQuantity": 1, "marketValue": -1768.0, "averagePrice": 19.98,
        "shortOpenProfitLoss": 230.05,
    }
    row = _row_from_raw("66502618", raw, is_spread=True)
    assert row.qty == -1
    assert row.mark == 17.68  # -1768 / (-1 * 100)
    assert row.is_spread is True and row.closeable is False  # spreads are view-only


def test_tracked_list_and_enrichment() -> None:
    _reset()
    _register_active_position(_proposal(), ["66502618", "47169783"], _accounts(), {"66502618": "OID1", "47169783": "OID2"})
    bare = _tracked_positions_response()  # no client -> no live P&L
    assert bare.mode == "tracked"
    assert len(bare.positions) == 2
    assert all(r.closeable and not r.is_spread for r in bare.positions)
    assert all(r.unrealized_pnl is None for r in bare.positions)

    class _PnlClient:
        def get_positions(self, account_hash):
            pnl = 150.0 if account_hash == "HASH1" else -80.0
            return [{"instrument": {"symbol": "SMCI  260626C00045000", "assetType": "OPTION"},
                     "longQuantity": 2, "averagePrice": 2.5, "marketValue": 700.0, "longOpenProfitLoss": pnl}]

    enriched = {r.account_id: r for r in _tracked_positions_response(client=_PnlClient()).positions}
    assert enriched["66502618"].unrealized_pnl == 150.0
    assert enriched["47169783"].unrealized_pnl == -80.0
    assert enriched["66502618"].avg == 2.5
    _reset()


class _CloseClient:
    def __init__(self):
        self.placed = []

    def place_order(self, account_hash, payload):
        self.placed.append((account_hash, payload))
        return {"broker_order_id": "NEW1"}

    def cancel_order(self, account_hash, order_id):
        pass


def _req():
    return CloseContractRequest(account_id="66502618", broker_symbol="SMCI  260626C00045000", qty=2, is_long=True, confirm_live_order=True)


def test_close_blocked_when_gate_closed(monkeypatch) -> None:
    _reset()
    monkeypatch.setattr(app, "discover_schwab_accounts", lambda cfg: ([SimpleNamespace(id="66502618", account_hash="HASH1", enabled=True)], []))
    client = _CloseClient()
    resp = _close_contract_response(_req(), client)
    assert resp.status in {"blocked", "dry_run"}
    assert client.placed == []  # nothing sent live
    assert resp.account_results[0].order_payload["orderType"] == "MARKET"


def test_close_submits_when_gate_open(monkeypatch) -> None:
    _reset()
    _register_active_position(_proposal(), ["66502618"], _accounts(), {"66502618": "OID1"})
    monkeypatch.setattr(app, "discover_schwab_accounts", lambda cfg: ([SimpleNamespace(id="66502618", account_hash="HASH1", enabled=True)], []))
    monkeypatch.setattr(app.settings.service, "execution_mode", "live", raising=False)
    monkeypatch.setattr(app.settings.service, "allow_live_orders", True, raising=False)
    monkeypatch.setattr(app.settings.service, "trading_enabled", True, raising=False)
    assert app.settings.service.live_gate_open is True
    client = _CloseClient()
    resp = _close_contract_response(_req(), client)
    assert resp.status == "submitted"
    assert len(client.placed) == 1
    assert client.placed[0][1]["orderLegCollection"][0]["instruction"] == "SELL_TO_CLOSE"
    # The closed contract was dropped from the tracker.
    assert "SMCI" not in app.active_positions
    _reset()
