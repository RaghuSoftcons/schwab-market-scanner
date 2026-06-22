"""
================================================================================
File:          test_trade_log.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 16:40 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 16:40 EST

Purpose:
    Tests the closed-trade log: realized P&L computation, JSONL persistence
    round-trip, the summary payload (P&L + win-rate by indicator/symbol +
    equity curve + history), and dedup-by-exit-order-id.

Change Log:
    2026-06-13 16:40 EST  v1.0.0  Initial tests (Claude + Raghu).
    2026-06-22 14:55 EST  v1.1.0  Scanner port: dropped the platform nt_schwab_bridge.app
                                  route/glue tests (/trades endpoints, _auto_record_exit_closes);
                                  the scanner's P&L glue lives in market_scanner.app and is
                                  covered separately. Pure TradeLogStore tests retained.
================================================================================
"""

from __future__ import annotations

from datetime import datetime, timezone

from nt_schwab_bridge.trade_log import TradeLogStore

UTC = timezone.utc


def test_realized_pnl_computed():
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "trades.jsonl")
    store = TradeLogStore(path)
    # Buy 2 @ 2.50, sell 2 @ 3.00 -> (3.00-2.50)*100*2 = +$100
    c = store.record_close(symbol="SPY", indicator="TwoLeggedPullback", account_id="m1",
                           entry_price=2.50, exit_price=3.00, contracts=2)
    assert c.realized_pnl == 100.0
    assert c.won is True
    # A loss
    c2 = store.record_close(symbol="QQQ", indicator="IntraBarBreakoutRetest", account_id="m1",
                            entry_price=2.0, exit_price=1.5, contracts=1)
    assert c2.realized_pnl == -50.0
    assert c2.won is False


def test_persistence_round_trip(tmp_path):
    path = tmp_path / "trades.jsonl"
    store = TradeLogStore(path)
    store.record_close(symbol="SPY", indicator="A", account_id="m1",
                       entry_price=2.0, exit_price=2.5, contracts=1)
    store.record_close(symbol="SPY", indicator="A", account_id="m1",
                       entry_price=2.0, exit_price=1.0, contracts=1)
    reloaded = TradeLogStore(path)
    assert len(reloaded.closes()) == 2
    summary = reloaded.summary()
    assert summary["pnl"]["trade_count"] == 2
    # close1 = (2.5-2.0)*100 = +50 ; close2 = (1.0-2.0)*100 = -100 ; net = -50
    assert summary["pnl"]["all_time"] == -50.0


def test_summary_winrate_by_indicator(tmp_path):
    store = TradeLogStore(tmp_path / "t.jsonl")
    store.record_close(symbol="SPY", indicator="TwoLeggedPullback", account_id="m1",
                       entry_price=2.0, exit_price=2.5, contracts=1)  # +50 win
    store.record_close(symbol="SPY", indicator="TwoLeggedPullback", account_id="m1",
                       entry_price=2.0, exit_price=2.5, contracts=1)  # +50 win
    store.record_close(symbol="ES", indicator="UltimateAIPro", account_id="m1",
                       entry_price=2.0, exit_price=1.5, contracts=1)  # -50 loss
    by_ind = store.summary()["winrate_by_indicator"]
    tlp = next(r for r in by_ind if r["name"] == "TwoLeggedPullback")
    assert tlp["win_rate"] == 1.0 and tlp["total"] == 2
    uap = next(r for r in by_ind if r["name"] == "UltimateAIPro")
    assert uap["win_rate"] == 0.0


def test_dedup_by_exit_order_id(tmp_path):
    store = TradeLogStore(tmp_path / "t.jsonl")
    first = store.record_close(symbol="SPY", indicator="A", account_id="m1",
                               entry_price=2.0, exit_price=2.5, contracts=1, dedup_key="EX1")
    assert first is not None
    # Same exit order id -> skipped.
    again = store.record_close(symbol="SPY", indicator="A", account_id="m1",
                               entry_price=2.0, exit_price=2.5, contracts=1, dedup_key="EX1")
    assert again is None
    assert len(store.closes()) == 1
    # Dedup survives reload.
    reloaded = TradeLogStore(tmp_path / "t.jsonl")
    assert reloaded.was_recorded("EX1") is True
    assert reloaded.record_close(symbol="SPY", indicator="A", account_id="m1",
                                 entry_price=2.0, exit_price=2.5, contracts=1, dedup_key="EX1") is None


