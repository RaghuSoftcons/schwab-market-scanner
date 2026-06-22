"""
File: test_balance_summary.py
Created: 2026-06-22 14:11 EST
Author: Claude (Anthropic) + Raghu
Version: 1.0.0
Last Modified: 2026-06-22 14:11 EST

Change Log:
- 2026-06-22 14:11 EST | 1.0.0 | Ported from Unified Platform: account-type-aware
  available-funds selection (MARGIN -> availableFunds, CASH -> cashAvailableForTrading)
  with conservative min(current, projected). Covers NIFTY and Individual regressions.
"""

from __future__ import annotations

from nt_schwab_bridge.schwab_adapter import _extract_account_balance_summary


def test_margin_account_available_prefers_margin_adjusted_available_funds() -> None:
    # NIFTY regression: a MARGIN account that reports BOTH a (gross, overstated)
    # cashAvailableForTrading and the (correct, margin-adjusted) availableFunds.
    # The summary must surface availableFunds -- $70.36, not the $301.77 gross cash.
    account = {
        "type": "MARGIN",
        "currentBalances": {
            "cashAvailableForTrading": 301.77,
            "availableFunds": 70.36,
            "buyingPower": 140.72,
            "cashBalance": 301.77,
        },
    }
    summary = _extract_account_balance_summary(account)
    assert summary["available_to_trade"] == 70.36
    assert summary["source"] == "currentBalances.availableFunds"


def test_available_uses_conservative_projected_over_current() -> None:
    # Individual-account regression: an actively-trading MARGIN account whose CURRENT
    # availableFunds ($521.87) overstates what Schwab actually shows. Schwab's displayed
    # "available funds" is the PROJECTED figure ($170.54) that nets out pending option buys.
    # The summary must surface the lower, conservative number.
    account = {
        "type": "MARGIN",
        "currentBalances": {"availableFunds": 521.87, "buyingPower": 2087.48, "cashBalance": 1071.87},
        "projectedBalances": {"availableFunds": 170.54, "buyingPower": 682.16},
    }
    summary = _extract_account_balance_summary(account)
    assert summary["available_to_trade"] == 170.54
    assert summary["source"] == "projectedBalances.availableFunds"
    # Buying power still reports the current snapshot (separate display field).
    assert summary["buying_power"] == 2087.48


def test_available_keeps_value_when_current_and_projected_match() -> None:
    # NIFTY-style account: current == projected, so the conservative min is unchanged.
    account = {
        "type": "MARGIN",
        "currentBalances": {"availableFunds": 70.36},
        "projectedBalances": {"availableFunds": 70.36},
    }
    summary = _extract_account_balance_summary(account)
    assert summary["available_to_trade"] == 70.36
    assert summary["source"] == "currentBalances.availableFunds"


def test_cash_account_available_prefers_cash_available_for_trading() -> None:
    # CASH accounts: settled tradeable cash (cashAvailableForTrading) is the right
    # figure and must win even when availableFunds is also present.
    account = {
        "type": "CASH",
        "currentBalances": {
            "cashAvailableForTrading": 4639.90,
            "availableFunds": 5000.00,
            "cashBalance": 4639.90,
        },
    }
    summary = _extract_account_balance_summary(account)
    assert summary["available_to_trade"] == 4639.90
    assert summary["source"] == "currentBalances.cashAvailableForTrading"


def test_unknown_type_defaults_to_cash_priority() -> None:
    # No type field -> treat as CASH: cashAvailableForTrading wins over availableFunds.
    account = {
        "currentBalances": {"cashAvailableForTrading": 1200.0, "availableFunds": 1500.0},
    }
    summary = _extract_account_balance_summary(account)
    assert summary["available_to_trade"] == 1200.0
    assert summary["source"] == "currentBalances.cashAvailableForTrading"
