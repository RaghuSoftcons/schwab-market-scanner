"""Open Positions panel: avg-field fix, spread detection, order#-based reconstruction, Target,
cancel-all selection. Ported from nt-bridge-v2 (2026-06-25)."""
from __future__ import annotations

from market_scanner.app import (
    _apply_spread_structure,
    _cancelable_order_ids_for_symbol,
    _mark_spread_legs,
    _parse_osi,
    _position_avg_mark_pnl,
    _reconstruct_orders_from_transactions,
    _stop_prices_for_orders,
    _target_prices_for_orders,
)

LONG_10C = "SOXS  260821C00010000"
SHORT_11C = "SOXS  260821C00011000"


def test_parse_osi() -> None:
    assert _parse_osi(LONG_10C) == ("260821", "C", 10.0)
    assert _parse_osi("bad") == ("", "", None)


def test_avg_uses_trade_price_and_recomputes_unrealized() -> None:
    # averagePrice (tax-lot) 28.71 differs from the real trade price (averageShortPrice 53.72):
    # avg must be the trade price and unrealized recomputed from (mark - avg), matching TOS.
    raw = {
        "instrument": {"assetType": "OPTION", "symbol": SHORT_11C},
        "longQuantity": 0, "shortQuantity": 1,
        "marketValue": -703.0,            # mark = 703/(1*100) = 7.03
        "averagePrice": 28.71,            # tax-lot basis (ignore)
        "averageShortPrice": 53.72,       # real fill (use)
        "shortOpenProfitLoss": -9999.0,   # built on tax-lot basis (ignore when bases differ)
    }
    avg, mark, unrealized = _position_avg_mark_pnl(raw)
    assert avg == 53.72
    assert mark == 7.03
    # short 1 lot: (mark - avg) * 100 * net, net = -1 -> (7.03 - 53.72)*100*-1 = +4669
    assert unrealized == round((7.03 - 53.72) * 100 * -1, 2)


def test_avg_uses_schwab_pnl_when_bases_match() -> None:
    raw = {
        "instrument": {"assetType": "OPTION", "symbol": LONG_10C},
        "longQuantity": 2, "shortQuantity": 0,
        "marketValue": 600.0,             # mark 3.0
        "averagePrice": 2.40, "averageLongPrice": 2.40,
        "longOpenProfitLoss": 120.0,
    }
    avg, mark, unrealized = _position_avg_mark_pnl(raw)
    assert avg == 2.40 and mark == 3.0
    assert unrealized == 120.0  # bases match -> use Schwab's open P&L verbatim


def test_mark_spread_legs_pairs_equal_qty_vertical() -> None:
    positions = [
        {"underlying": "SOXS", "symbol": LONG_10C, "quantity": 1},
        {"underlying": "SOXS", "symbol": SHORT_11C, "quantity": -1},
    ]
    _mark_spread_legs(positions)
    assert positions[0]["is_spread_leg"] and positions[1]["is_spread_leg"]
    assert positions[0]["spread_id"] == positions[1]["spread_id"]


def test_mark_spread_legs_qty_mismatch_flags_aggregated() -> None:
    positions = [
        {"underlying": "SOXS", "symbol": LONG_10C, "quantity": 7},   # +7 serving a -1 short
        {"underlying": "SOXS", "symbol": SHORT_11C, "quantity": -1},
    ]
    _mark_spread_legs(positions)
    assert positions[0]["spread_aggregated"] and positions[1]["spread_aggregated"]
    assert "spread_id" not in positions[0]  # not a clean N:N -> not combined


def test_standalone_long_not_marked_as_spread() -> None:
    positions = [{"underlying": "SOXS", "symbol": LONG_10C, "quantity": 4}]
    _mark_spread_legs(positions)
    assert positions[0]["is_spread_leg"] is False


def test_reconstruct_orders_from_transactions() -> None:
    txns = [
        {"type": "TRADE", "orderId": 111, "transferItems": [
            {"instrument": {"assetType": "OPTION", "symbol": LONG_10C, "underlyingSymbol": "SOXS"},
             "positionEffect": "OPENING", "amount": 1, "price": 2.30},
            {"instrument": {"assetType": "OPTION", "symbol": SHORT_11C, "underlyingSymbol": "SOXS"},
             "positionEffect": "OPENING", "amount": -1, "price": 0.14},
        ]},
        {"type": "TRADE", "orderId": 222, "transferItems": [
            {"instrument": {"assetType": "OPTION", "symbol": LONG_10C, "underlyingSymbol": "SOXS"},
             "positionEffect": "OPENING", "amount": 5, "price": 0.39},
        ]},
        # RECEIVE_AND_DELIVER (assignment/expiration) must be excluded — no phantom $0 leg.
        {"type": "RECEIVE_AND_DELIVER", "orderId": 333, "transferItems": [
            {"instrument": {"assetType": "OPTION", "symbol": LONG_10C}, "positionEffect": "OPENING", "amount": 1, "price": 0.0},
        ]},
    ]
    out = _reconstruct_orders_from_transactions(txns)
    assert len(out["spreads"]) == 1 and len(out["singles"]) == 1
    spread = out["spreads"][0]
    assert spread["long_fill"] == 2.30 and spread["short_fill"] == 0.14 and spread["qty"] == 1
    assert out["singles"][0]["fill"] == 0.39 and out["singles"][0]["qty"] == 5


def test_apply_spread_structure_splits_shared_strike() -> None:
    # A held +6 of the 10C is really 1 spread leg (10/11) + a 5-lot single, per the order structure.
    positions = [
        {"symbol": LONG_10C, "underlying": "SOXS", "asset_type": "OPTION", "quantity": 6, "average_price": 0.7, "mark": 1.0, "market_value": 600.0},
        {"symbol": SHORT_11C, "underlying": "SOXS", "asset_type": "OPTION", "quantity": -1, "average_price": 0.14, "mark": 0.2, "market_value": -20.0},
    ]
    structure = {
        "spreads": [{"long_symbol": LONG_10C, "short_symbol": SHORT_11C, "long_fill": 2.30, "short_fill": 0.14, "qty": 1, "order_id": "111"}],
        "singles": [{"symbol": LONG_10C, "fill": 0.39, "qty": 5, "order_id": "222"}],
    }
    out = _apply_spread_structure(positions, structure)
    spread_legs = [r for r in out if r.get("spread_id") == "ord-111"]
    singles = [r for r in out if not r.get("spread_id")]
    assert len(spread_legs) == 2
    assert any(abs(r["quantity"] - 5) < 1e-9 and r["average_price"] == 0.39 for r in singles)
    long_leg = next(r for r in spread_legs if r["quantity"] > 0)
    assert long_leg["average_price"] == 2.30 and long_leg["from_structure"]


def test_cancelable_order_ids_reads_oco_children() -> None:
    orders = [
        {"orderId": 1, "status": "WORKING", "orderType": "TRIGGER", "orderLegCollection": [
            {"instruction": "BUY_TO_OPEN", "instrument": {"symbol": LONG_10C}}],
         "childOrderStrategies": [{"orderStrategyType": "OCO", "childOrderStrategies": [
             {"orderType": "LIMIT", "orderLegCollection": [{"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": LONG_10C}}]}]}]},
        {"orderId": 2, "status": "FILLED", "orderLegCollection": [
            {"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": LONG_10C}}]},  # terminal -> skip
    ]
    assert _cancelable_order_ids_for_symbol(orders, LONG_10C) == [1]


def test_target_prices_for_orders_reads_closing_limit() -> None:
    orders = [
        {"status": "WORKING", "orderType": "LIMIT", "price": "1.20", "orderLegCollection": [
            {"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": LONG_10C}}]},
        {"status": "WORKING", "orderType": "STOP", "stopPrice": "0.50", "orderLegCollection": [
            {"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": LONG_10C}}]},  # stop, not a target
    ]
    targets = _target_prices_for_orders(orders)
    assert targets[LONG_10C.replace(" ", "")] == 1.20


def test_stop_prices_for_orders_reads_closing_stop() -> None:
    orders = [
        {"status": "WORKING", "orderType": "STOP", "stopPrice": "0.50", "orderLegCollection": [
            {"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": LONG_10C}}]},
        {"status": "WORKING", "orderType": "LIMIT", "price": "1.20", "orderLegCollection": [
            {"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": LONG_10C}}]},  # target, not a stop
    ]
    stops = _stop_prices_for_orders(orders)
    assert stops[LONG_10C.replace(" ", "")] == 0.50


def test_otoco_bracket_target_and_stop_from_oco_children() -> None:
    # An OTOCO entry: TRIGGER -> OCO[ target LIMIT, stop STOP ]. Both columns read the children.
    orders = [{"status": "WORKING", "orderType": "TRIGGER", "orderLegCollection": [
        {"instruction": "BUY_TO_OPEN", "instrument": {"symbol": LONG_10C}}],
        "childOrderStrategies": [{"orderStrategyType": "OCO", "childOrderStrategies": [
            {"status": "WORKING", "orderType": "LIMIT", "price": "1.20", "orderLegCollection": [
                {"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": LONG_10C}}]},
            {"status": "WORKING", "orderType": "STOP", "stopPrice": "0.50", "orderLegCollection": [
                {"instruction": "SELL_TO_CLOSE", "instrument": {"symbol": LONG_10C}}]},
        ]}]}]
    key = LONG_10C.replace(" ", "")
    assert _target_prices_for_orders(orders)[key] == 1.20
    assert _stop_prices_for_orders(orders)[key] == 0.50
