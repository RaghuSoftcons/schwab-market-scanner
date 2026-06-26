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
- 4.0.0 (2026-06-25) Close-on-Reversal hardening port: tests for _resting_close_order_ids (OTOCO
  child-bracket discovery), _confirm_orders_cleared (bounded poll), cancel+confirm-before-MARKET
  close, and keep-tracked-on-failure. Fake order client models cancellation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import market_scanner.app as app
from market_scanner.app import (
    _close_contract_response,
    _confirm_orders_cleared,
    _register_active_position,
    _resting_close_order_ids,
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


# ---- Close-on-Reversal hardening (ported from nt-bridge-v2, 2026-06-25) ----

_SMCI = "SMCI  260626C00045000"


def test_resting_close_order_ids_finds_otoco_child_bracket() -> None:
    # A FILLED OTOCO entry whose nested child OCO still rests: discovery must return the OCO (the
    # outermost cancelable ancestor of the closing legs), NOT the individual legs or the filled entry.
    orders = [{
        "orderId": "ENTRY", "status": "FILLED", "orderType": "TRIGGER",
        "orderLegCollection": [{"instruction": "BUY_TO_OPEN", "instrument": {"symbol": _SMCI}}],
        "childOrderStrategies": [{
            "orderId": "OCO1", "status": "WORKING", "orderStrategyType": "OCO",
            "childOrderStrategies": [
                {"orderId": "T1", "status": "WORKING", "orderType": "LIMIT",
                 "orderLegCollection": [{"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": _SMCI}}]},
                {"orderId": "S1", "status": "WORKING", "orderType": "STOP",
                 "orderLegCollection": [{"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": _SMCI}}]},
            ],
        }],
    }]
    assert _resting_close_order_ids(orders, [_SMCI]) == ["OCO1"]


def test_confirm_orders_cleared_resolves_after_cancel() -> None:
    class _C:
        def __init__(self):
            self.calls = 0

        def get_orders(self, account_hash, frm, to):
            self.calls += 1
            return [{"orderId": "OCO1", "status": "WORKING" if self.calls == 1 else "CANCELED"}]

    assert _confirm_orders_cleared(_C(), "HASH1", ["OCO1"], "f", "t", timeout_s=1.0, step_s=0.01) is True


def test_confirm_orders_cleared_times_out_when_never_cleared() -> None:
    class _C:
        def get_orders(self, account_hash, frm, to):
            return [{"orderId": "OCO1", "status": "WORKING"}]

    assert _confirm_orders_cleared(_C(), "HASH1", ["OCO1"], "f", "t", timeout_s=0.05, step_s=0.01) is False


class _BracketClient:
    """Models a live order book: one resting OCO holding the closing legs; cancel_order marks it
    CANCELED so _confirm_orders_cleared resolves; place_order can be forced to fail."""

    def __init__(self, fail_place=False):
        self.fail_place = fail_place
        self.placed = []
        self.canceled = []
        self.orders = [{
            "orderId": "OCO1", "status": "WORKING", "orderStrategyType": "OCO",
            "childOrderStrategies": [
                {"orderId": "T1", "status": "WORKING", "orderType": "LIMIT",
                 "orderLegCollection": [{"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": _SMCI}}]},
                {"orderId": "S1", "status": "WORKING", "orderType": "STOP",
                 "orderLegCollection": [{"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": _SMCI}}]},
            ],
        }]

    def get_positions(self, account_hash):
        return [{"instrument": {"symbol": _SMCI, "assetType": "OPTION", "underlyingSymbol": "SMCI"},
                 "longQuantity": 2, "shortQuantity": 0, "averagePrice": 2.5,
                 "marketValue": 500.0, "longOpenProfitLoss": 0.0}]

    def get_orders(self, account_hash, frm, to):
        import copy
        return copy.deepcopy(self.orders)

    def cancel_order(self, account_hash, order_id):
        self.canceled.append(str(order_id))

        def mark(o):
            if str(o.get("orderId")) == str(order_id):
                o["status"] = "CANCELED"
            for c in o.get("childOrderStrategies") or []:
                mark(c)

        for o in self.orders:
            mark(o)

    def place_order(self, account_hash, payload):
        if self.fail_place:
            raise app.SchwabApiError("oversold")
        self.placed.append((account_hash, payload))
        return {"broker_order_id": "MKT1"}


def _live_close_env(monkeypatch) -> None:
    monkeypatch.setattr(app, "discover_schwab_accounts",
                        lambda cfg: ([SimpleNamespace(id="66502618", account_hash="HASH1", enabled=True)], []))
    monkeypatch.setattr(app.settings.service, "execution_mode", "live", raising=False)
    monkeypatch.setattr(app.settings.service, "allow_live_orders", True, raising=False)
    monkeypatch.setattr(app.settings.service, "trading_enabled", True, raising=False)


def test_manual_close_cancels_bracket_then_market_closes_when_live(monkeypatch) -> None:
    _reset()
    _register_active_position(_proposal(), ["66502618"], _accounts(), {"66502618": "OID1"})
    _live_close_env(monkeypatch)
    client = _BracketClient()
    resp = _close_contract_response(_req(), client)
    assert resp.status == "submitted"
    assert "OCO1" in client.canceled                       # discovered + cancelled the resting bracket
    assert len(client.placed) == 1                          # then flattened
    assert client.placed[0][1]["orderType"] == "MARKET"
    assert "SMCI" not in app.active_positions               # untracked on a clean close
    _reset()


def test_manual_close_keeps_position_tracked_when_close_fails(monkeypatch) -> None:
    _reset()
    _register_active_position(_proposal(), ["66502618"], _accounts(), {"66502618": "OID1"})
    _live_close_env(monkeypatch)
    client = _BracketClient(fail_place=True)
    resp = _close_contract_response(_req(), client)
    assert resp.status == "blocked"
    assert any("kept_tracked" in r for r in resp.account_results[0].reasons)
    assert "SMCI" in app.active_positions                   # NOT untracked on a failed close
    _reset()
