# ============================================================================
# File:          test_registration_stop_mgmt.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
# Purpose:       _registration_stop_mgmt gates which sends get active stop
#                management: only single-leg OTOCO entries with a real stop and a
#                non-fixed mode arm; everything else stays a plain fixed OCO (None).
# ============================================================================
from types import SimpleNamespace

from market_scanner.app import _registration_stop_mgmt


def _proposal(structure="single", n_legs=1):
    return SimpleNamespace(structure=structure, legs=[object()] * n_legs)


def _call(**over):
    kw = dict(proposal=_proposal(), otoco_applied=True, target_percentages=[20.0, 50.0],
              stop_mode="be_then_trail", trail_start_percent=10, trail_distance_percent=8,
              stop_loss_percent=50)
    kw.update(over)
    return _registration_stop_mgmt(**kw)


def test_single_leg_otoco_nonfixed_arms():
    sm = _call()
    assert sm["mode"] == "be_then_trail"
    assert sm["start_pct"] == 10 and sm["trail_pct"] == 8 and sm["target_pct"] == 20.0
    assert sm["armed_hashes"] == [] and sm["arm_fails"] == {}


def test_fixed_mode_returns_none():
    assert _call(stop_mode="fixed") is None


def test_non_otoco_returns_none():
    assert _call(otoco_applied=False) is None


def test_vertical_returns_none():
    assert _call(proposal=_proposal(structure="debit_vertical", n_legs=2)) is None


def test_no_stop_loss_returns_none():
    assert _call(stop_loss_percent=0) is None
