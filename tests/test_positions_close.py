"""
File: test_positions_close.py
Created: 2026-06-22 15:20 EST
Author: Claude (Anthropic) + Raghu
Version: 1.0.0
Last Modified: 2026-06-22 15:20 EST

Change Log:
- 2026-06-22 15:20 EST | 1.0.0 | Open-positions aggregation (#9a), MARKET close payload (#9b),
  and triple-lock/confirm gating for Close-now. Uses a stub Schwab client (no live calls).
"""

from __future__ import annotations

from types import SimpleNamespace

from market_scanner.app import (
    _aggregate_positions,
    _market_close_order_payload,
    _normalize_position,
    _close_position_response,
)
from market_scanner.models import ClosePositionRequest


def _account(account_id="66502618", account_hash="HASH", enabled=True):
    return SimpleNamespace(id=account_id, account_hash=account_hash, enabled=enabled, label="Individual")


def _raw_long_call():
    return {
        "instrument": {"symbol": "SMCI  260626C00045000", "assetType": "OPTION", "underlyingSymbol": "SMCI"},
        "longQuantity": 2,
        "shortQuantity": 0,
        "averagePrice": 2.50,
        "marketValue": 700.0,
        "longOpenProfitLoss": 200.0,
    }


def test_normalize_position_long_call() -> None:
    view = _normalize_position(_raw_long_call(), _account())
    assert view is not None
    assert view.symbol == "SMCI  260626C00045000"
    assert view.underlying == "SMCI"
    assert view.net_qty == 2
    assert view.unrealized_pnl == 200.0
    assert view.account_label == "Individual"  # alias from ACCOUNT_ALIASES


def test_market_close_payload_long_is_sell_to_close() -> None:
    payload = _market_close_order_payload("SMCI  260626C00045000", 2, is_long=True)
    assert payload["orderType"] == "MARKET"
    assert payload["orderStrategyType"] == "SINGLE"
    leg = payload["orderLegCollection"][0]
    assert leg["instruction"] == "SELL_TO_CLOSE"
    assert leg["quantity"] == 2


def test_market_close_payload_short_is_buy_to_close() -> None:
    payload = _market_close_order_payload("SMCI  260626P00045000", 1, is_long=False)
    assert payload["orderLegCollection"][0]["instruction"] == "BUY_TO_CLOSE"


class _StubClient:
    def __init__(self, positions):
        self._positions = positions
        self.placed = []

    def get_positions(self, account_hash):
        return self._positions


def test_aggregate_positions_skips_flat() -> None:
    flat = dict(_raw_long_call(), longQuantity=0, shortQuantity=0)
    client = _StubClient([_raw_long_call(), flat])
    views, errors = _aggregate_positions([_account()], client)
    assert errors == []
    assert len(views) == 1  # the flat one is dropped


def test_close_is_blocked_without_live_gate() -> None:
    # The triple-lock is closed in dry-run config, so close must NOT submit; it returns the payload.
    client = _StubClient([_raw_long_call()])
    resp = _close_position_response(
        symbol="SMCI  260626C00045000",
        accounts=[_account()],
        request=ClosePositionRequest(selected_account_ids=["66502618"], confirm_live_order=True),
        order_client=client,
    )
    assert resp.status in {"blocked", "dry_run"}
    assert resp.account_results
    result = resp.account_results[0]
    assert result.status in {"blocked", "dry_run"}
    assert result.order_payload is not None
    assert result.order_payload["orderType"] == "MARKET"
    # No live order was placed against the stub client.
    assert client.placed == []


def test_close_reports_no_position_for_unknown_symbol() -> None:
    client = _StubClient([_raw_long_call()])
    resp = _close_position_response(
        symbol="NVDA",
        accounts=[_account()],
        request=ClosePositionRequest(confirm_live_order=False),
        order_client=client,
    )
    assert resp.status == "blocked"
    assert any("No open position" in note for note in resp.notes)
