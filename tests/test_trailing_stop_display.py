# ============================================================================
# File:          test_trailing_stop_display.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
# Purpose:       Open Positions "Stop" column must show a value for an ARMED native
#                TRAILING_STOP (which has stopPriceOffset, no stopPrice) — effective
#                trigger = mark - offset — instead of going blank. Mirrors the Unified 5b.
# ============================================================================
from market_scanner.app import _stop_prices_for_orders, _resolve_stop_marker

SYM = "DIA   260702C00523000"
SYMK = "DIA260702C00523000"


def _leg():
    return {"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": SYM}}


def test_fixed_stop_reads_stopprice():
    order = {"status": "WORKING", "orderType": "STOP", "stopPrice": 1.06, "orderLegCollection": [_leg()]}
    assert _stop_prices_for_orders([order]) == {SYMK: 1.06}


def test_trailing_stop_emits_trail_marker():
    order = {"status": "WORKING", "orderType": "TRAILING_STOP", "stopPriceOffset": 0.30,
             "orderLegCollection": [_leg()]}
    assert _stop_prices_for_orders([order]) == {SYMK: ("trail", 0.30)}


def test_trailing_stop_with_stopprice_prefers_price():
    order = {"status": "WORKING", "orderType": "TRAILING_STOP", "stopPrice": 1.85,
             "stopPriceOffset": 0.30, "orderLegCollection": [_leg()]}
    assert _stop_prices_for_orders([order]) == {SYMK: 1.85}


def test_resolve_trailing_marker_computes_effective_stop():
    eff, trailing, offset = _resolve_stop_marker(("trail", 0.30), 2.19)
    assert eff == 1.89 and trailing is True and offset == 0.30


def test_resolve_fixed_marker_unchanged():
    assert _resolve_stop_marker(1.06, 2.19) == (1.06, False, None)


def test_resolve_trailing_no_mark_is_none_not_crash():
    eff, trailing, offset = _resolve_stop_marker(("trail", 0.30), None)
    assert eff is None and trailing is True and offset == 0.30
