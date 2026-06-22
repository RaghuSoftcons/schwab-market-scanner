"""
================================================================================
File:          test_dashboard_stats.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 15:00 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 15:00 EST

Purpose:
    Tests the dashboard data layer: P&L windowing (today/week/month/all-time),
    win-rate, cumulative equity curve ordering, and trade-history filtering.

Change Log:
    2026-06-13 15:00 EST  v1.0.0  Initial tests (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nt_schwab_bridge.dashboard_stats import (
    SystemHealth,
    ServiceProbe,
    TradeClose,
    compute_pnl,
    equity_curve,
    trade_history,
)

UTC = timezone.utc
# Anchor "now" to a Wednesday so week math is unambiguous.
NOW = datetime(2026, 6, 17, 15, 0, 0, tzinfo=UTC)  # Wed 2026-06-17


def _c(days_ago, pnl, won, symbol="ES", indicator="IntraBarBreakoutRetest", account="m1"):
    return TradeClose(
        closed_at=NOW - timedelta(days=days_ago),
        symbol=symbol,
        indicator=indicator,
        account_id=account,
        realized_pnl=pnl,
        won=won,
    )


def test_pnl_windows():
    closes = [
        _c(0, 100, True),     # today
        _c(1, -50, False),    # this week (Tue)
        _c(8, 200, True),     # last week -> month only
        _c(40, 75, True),     # >month -> all-time only
    ]
    s = compute_pnl(closes, now=NOW)
    assert s.today == 100
    assert s.week == 50          # 100 - 50
    assert s.month == 250        # 100 - 50 + 200
    assert s.all_time == 325     # + 75
    assert s.trade_count == 4
    assert s.wins == 3 and s.losses == 1
    assert s.win_rate == 0.75


def test_pnl_empty():
    s = compute_pnl([], now=NOW)
    assert s.as_dict()["all_time"] == 0.0
    assert s.win_rate is None


def test_equity_curve_is_cumulative_and_sorted():
    closes = [_c(0, 100, True), _c(2, -40, False), _c(1, 30, True)]
    curve = equity_curve(closes)
    # Sorted oldest first: day -2 (-40), day -1 (+30), day 0 (+100)
    assert [p["pnl"] for p in curve] == [-40, 30, 100]
    assert [p["cumulative"] for p in curve] == [-40, -10, 90]


def test_trade_history_filters():
    closes = [
        _c(0, 100, True, symbol="ES", indicator="A", account="m1"),
        _c(1, -50, False, symbol="QQQ", indicator="B", account="m2"),
        _c(2, 20, True, symbol="ES", indicator="B", account="m1"),
    ]
    assert len(trade_history(closes, symbol="ES")) == 2
    assert len(trade_history(closes, indicator="B")) == 2
    assert len(trade_history(closes, account_id="m2")) == 1
    assert len(trade_history(closes, result="loss")) == 1
    # newest first
    rows = trade_history(closes)
    assert rows[0]["closed_at"] > rows[-1]["closed_at"]


def test_system_health_dict():
    h = SystemHealth(
        token_status="valid",
        token_read_only=False,
        services=[ServiceProbe("token", True), ServiceProbe("bridge", True)],
        quote_freshness_seconds=12.0,
        stale_quote_count=4,
        total_quote_count=202,
    )
    d = h.as_dict()
    assert d["all_up"] is True
    assert d["stale_quotes"] == "4 of 202"
    assert d["token_read_only"] is False
