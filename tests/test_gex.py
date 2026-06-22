"""
================================================================================
File:          test_gex.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 15:25 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 15:25 EST

Purpose:
    Tests GEX computation from chain rows: positive vs negative net GEX, the
    momentum support mapping (negative supports / positive opposes), the neutral
    band, skipping of missing-greek rows, and the Schwab-chain adapter.

Change Log:
    2026-06-13 15:25 EST  v1.0.0  Initial tests (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

from dataclasses import dataclass

from nt_schwab_bridge.gex import (
    GexConfig,
    OptionGreekRow,
    compute_gex,
    gex_support_from_schwab_chain,
)


def _rows(call_gamma_oi, put_gamma_oi):
    rows = []
    for gamma, oi in call_gamma_oi:
        rows.append(OptionGreekRow(is_call=True, strike=500, gamma=gamma, open_interest=oi))
    for gamma, oi in put_gamma_oi:
        rows.append(OptionGreekRow(is_call=False, strike=500, gamma=gamma, open_interest=oi))
    return rows


def test_positive_gex_opposes_momentum():
    # Heavy call gamma -> net positive -> pinning -> opposes a momentum signal.
    rows = _rows(call_gamma_oi=[(0.05, 1000)], put_gamma_oi=[(0.05, 100)])
    res = compute_gex(rows, spot=500)
    assert res.net_gex > 0
    assert res.regime == "positive"
    assert res.support == "opposes"


def test_negative_gex_supports_momentum():
    # Heavy put gamma -> net negative -> amplifies moves -> supports momentum.
    rows = _rows(call_gamma_oi=[(0.05, 100)], put_gamma_oi=[(0.05, 1000)])
    res = compute_gex(rows, spot=500)
    assert res.net_gex < 0
    assert res.regime == "negative"
    assert res.support == "supports"


def test_neutral_band():
    rows = _rows(call_gamma_oi=[(0.05, 500)], put_gamma_oi=[(0.05, 500)])
    res = compute_gex(rows, spot=500, config=GexConfig(neutral_band=1.0))
    assert res.net_gex == 0
    assert res.regime == "neutral"
    assert res.support == "neutral"


def test_skips_missing_greeks():
    rows = [
        OptionGreekRow(is_call=True, strike=500, gamma=0.0, open_interest=1000),   # gamma 0 -> skip
        OptionGreekRow(is_call=True, strike=500, gamma=0.05, open_interest=0),     # OI 0 -> skip
        OptionGreekRow(is_call=True, strike=500, gamma=0.05, open_interest=1000),  # counted
    ]
    res = compute_gex(rows, spot=500)
    assert res.contracts_used == 1


def test_mean_reversion_inverts_support():
    rows = _rows(call_gamma_oi=[(0.05, 1000)], put_gamma_oi=[(0.05, 100)])
    res = compute_gex(rows, spot=500, config=GexConfig(momentum_strategy=False))
    assert res.regime == "positive"
    assert res.support == "supports"  # inverted vs momentum default


@dataclass
class _FakeContract:
    right: str
    strike: float
    gamma: float
    open_interest: int


def test_schwab_chain_adapter():
    contracts = [
        _FakeContract("CALL", 500, 0.05, 100),
        _FakeContract("PUT", 500, 0.05, 1000),
    ]
    verdict = gex_support_from_schwab_chain(contracts, spot=500)
    assert verdict == "supports"  # net negative


def test_adapter_returns_none_without_greeks():
    @dataclass
    class _NoGreek:
        right: str = "CALL"
        strike: float = 500.0

    assert gex_support_from_schwab_chain([_NoGreek()], spot=500) is None


def test_call_and_put_walls():
    rows = [
        OptionGreekRow(is_call=True, strike=505, gamma=0.05, open_interest=2000),   # call wall
        OptionGreekRow(is_call=True, strike=510, gamma=0.05, open_interest=100),
        OptionGreekRow(is_call=False, strike=495, gamma=0.05, open_interest=3000),  # put wall
        OptionGreekRow(is_call=False, strike=490, gamma=0.05, open_interest=100),
    ]
    res = compute_gex(rows, spot=500)
    assert res.call_wall == 505
    assert res.put_wall == 495
    assert len(res.per_strike) == 4


def test_min_open_interest_filter():
    rows = [
        OptionGreekRow(is_call=True, strike=505, gamma=0.05, open_interest=50),   # below min
        OptionGreekRow(is_call=True, strike=510, gamma=0.05, open_interest=500),  # kept
    ]
    res = compute_gex(rows, spot=500, config=GexConfig(min_open_interest=100))
    assert res.contracts_used == 1
    assert all(s.strike == 510 for s in res.per_strike)


def test_gamma_flip_estimate_between_put_and_call_dominance():
    # Lower strikes put-dominated (net negative), higher strikes call-dominated
    # (net positive) -> flip estimate lands between them.
    rows = [
        OptionGreekRow(is_call=False, strike=490, gamma=0.05, open_interest=2000),
        OptionGreekRow(is_call=False, strike=495, gamma=0.05, open_interest=2000),
        OptionGreekRow(is_call=True, strike=505, gamma=0.05, open_interest=2000),
        OptionGreekRow(is_call=True, strike=510, gamma=0.05, open_interest=2000),
    ]
    res = compute_gex(rows, spot=500)
    assert res.gamma_flip is not None
    assert 495 <= res.gamma_flip <= 505


def test_as_dict_includes_new_fields():
    rows = [OptionGreekRow(is_call=True, strike=505, gamma=0.05, open_interest=500)]
    d = compute_gex(rows, spot=500).as_dict()
    assert "call_wall" in d and "put_wall" in d
    assert "gamma_flip_estimate" in d
    assert isinstance(d["per_strike"], list)
