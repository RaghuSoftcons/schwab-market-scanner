# ============================================================================
# File:          test_trailing.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
# Purpose:       Lock the ported trailing-stop monitor (market-closed, so no live
#                verify): payload shapes, resting-OCO discovery, the arm cancel→place
#                sequence with restore-on-failure, and the evaluate_trailing_arms
#                decision logic (arm on profit cross, idempotency, 3-strike give-up).
# ============================================================================
from datetime import datetime, timezone

import pytest

from market_scanner import trailing
from market_scanner.trailing import _TrailArmRejected

SYM = "DIA   260702C00523000"
NOW = datetime(2026, 7, 1, 18, 0, 0, tzinfo=timezone.utc)


# ---- payload builders -------------------------------------------------------
def test_breakeven_stop_is_stop_at_entry():
    p = trailing.breakeven_stop_payload(SYM, 5, 2.00)
    assert p["orderType"] == "STOP" and p["stopPrice"] == "2.00" and p["quantity"] == 5
    assert p["orderLegCollection"][0]["instruction"] == "SELL_TO_CLOSE"


def test_trailing_stop_is_mark_linked_dollar_offset():
    p = trailing.trailing_stop_payload(SYM, 3, 8.0, 2.50)
    assert p["orderType"] == "TRAILING_STOP"
    assert p["stopPriceLinkBasis"] == "MARK" and p["stopPriceLinkType"] == "VALUE"
    assert p["stopPriceOffset"] == 0.20  # 2.50 * 8%


def test_stop_replacement_fixed_returns_none():
    assert trailing.stop_replacement_payload("fixed", SYM, 5, 2.0, 8.0) is None


def test_build_arm_oco_be_then_trail_uses_trailing_child():
    sm = {"mode": "be_then_trail", "trail_pct": 8.0}
    oco = trailing.build_arm_oco_payload(sm, SYM, 5, 2.00, 2.40)
    assert oco["orderStrategyType"] == "OCO"
    kinds = {c["orderType"] for c in oco["childOrderStrategies"]}
    assert kinds == {"LIMIT", "TRAILING_STOP"}


def test_build_arm_oco_fixed_returns_none():
    assert trailing.build_arm_oco_payload({"mode": "fixed"}, SYM, 5, 2.0, 2.4) is None


def test_is_transient_detects_auth_and_5xx():
    assert trailing.is_transient_arm_error(Exception("HTTP 503 gateway"))
    assert trailing.is_transient_arm_error(Exception("token expired"))
    assert not trailing.is_transient_arm_error(Exception("insufficient shares to sell"))


# ---- resting OCO discovery --------------------------------------------------
def _oco_order(order_id, limit, stop, qty=5, status="WORKING"):
    leg = [{"instruction": "SELL_TO_CLOSE", "quantity": qty, "instrument": {"symbol": SYM, "assetType": "OPTION"}}]
    return {
        "orderId": order_id, "status": status, "orderStrategyType": "OCO",
        "childOrderStrategies": [
            {"orderType": "LIMIT", "price": str(limit), "orderLegCollection": leg},
            {"orderType": "STOP", "stopPrice": str(stop), "orderLegCollection": leg},
        ],
    }


def test_resting_oco_top_level():
    got = trailing.resting_oco_for_symbol([_oco_order("111", 2.40, 1.00)], SYM)
    assert got == {"cancel_id": "111", "limit": 2.40, "stop": 1.00, "qty": 5}


def test_resting_oco_nested_under_trigger():
    trigger = {"orderId": "999", "status": "FILLED", "orderStrategyType": "TRIGGER",
               "childOrderStrategies": [_oco_order("222", 2.40, 1.00)]}
    got = trailing.resting_oco_for_symbol([trigger], SYM)
    assert got["cancel_id"] == "222"


def test_resting_oco_ignores_other_symbol():
    other = _oco_order("333", 2.40, 1.00)
    for c in other["childOrderStrategies"]:
        c["orderLegCollection"][0]["instrument"]["symbol"] = "SPY   260702C00500000"
    assert trailing.resting_oco_for_symbol([other], SYM) is None


# ---- fake Schwab client -----------------------------------------------------
class FakeClient:
    def __init__(self, orders=None, positions=None, place_exc=None, cancel_exc=None):
        self._orders = orders or []
        self._positions = positions or []
        self.place_calls = []
        self.cancel_calls = []
        self._place_exc = place_exc
        self._cancel_exc = cancel_exc

    def get_orders(self, account_hash, frm, to):
        return self._orders

    def get_positions(self, account_hash):
        return self._positions

    def cancel_order(self, account_hash, order_id):
        self.cancel_calls.append(order_id)
        if self._cancel_exc:
            raise self._cancel_exc

    def place_order(self, account_hash, payload):
        self.place_calls.append(payload)
        if self._place_exc:
            raise self._place_exc
        return {"broker_order_id": "NEW123"}


# ---- arm_account_stop -------------------------------------------------------
def test_arm_cancels_then_places_new_oco():
    c = FakeClient(orders=[_oco_order("111", 2.40, 1.00)])
    sm = {"mode": "be_then_trail", "trail_pct": 8.0}
    oid = trailing.arm_account_stop(
        client=c, account_hash="HASH01", broker_symbol=SYM, qty=5, entry_avg=2.00,
        stop_mgmt=sm, frm="a", to="b", sleep=lambda s: None,
    )
    assert oid == "NEW123"
    assert c.cancel_calls == ["111"]
    assert len(c.place_calls) == 1 and c.place_calls[0]["orderStrategyType"] == "OCO"


def test_arm_no_resting_oco_is_skip():
    c = FakeClient(orders=[])
    oid = trailing.arm_account_stop(
        client=c, account_hash="H", broker_symbol=SYM, qty=5, entry_avg=2.0,
        stop_mgmt={"mode": "trailing", "trail_pct": 8}, frm="a", to="b", sleep=lambda s: None,
    )
    assert oid is None and c.cancel_calls == []


def test_arm_place_reject_restores_fixed_oco_and_raises():
    c = FakeClient(orders=[_oco_order("111", 2.40, 1.00)], place_exc=Exception("order rejected: bad price"))
    with pytest.raises(_TrailArmRejected):
        trailing.arm_account_stop(
            client=c, account_hash="H", broker_symbol=SYM, qty=5, entry_avg=2.0,
            stop_mgmt={"mode": "breakeven"}, frm="a", to="b", sleep=lambda s: None,
        )
    # first place = armed (raised), second place = the restored fixed OCO
    assert len(c.place_calls) == 2
    restored = c.place_calls[1]
    assert restored["orderStrategyType"] == "OCO"
    assert any(ch.get("stopPrice") == "1.00" for ch in restored["childOrderStrategies"])


def test_arm_transient_place_failure_returns_none():
    c = FakeClient(orders=[_oco_order("111", 2.40, 1.00)], place_exc=Exception("HTTP 503"))
    oid = trailing.arm_account_stop(
        client=c, account_hash="H", broker_symbol=SYM, qty=5, entry_avg=2.0,
        stop_mgmt={"mode": "breakeven"}, frm="a", to="b", sleep=lambda s: None,
    )
    assert oid is None  # transient → retry, not a rejection


# ---- evaluate_trailing_arms -------------------------------------------------
def _position(mark, avg=2.00, qty=5):
    return {
        "instrument": {"symbol": SYM, "assetType": "OPTION"},
        "longQuantity": qty, "shortQuantity": 0,
        "marketValue": mark * qty * 100, "averageLongPrice": avg, "averagePrice": avg,
        "longOpenProfitLoss": (mark - avg) * qty * 100,
    }


def _avg_mark_fn(raw):
    net = raw["longQuantity"] - raw["shortQuantity"]
    mark = round(raw["marketValue"] / (net * 100), 2)
    return raw["averageLongPrice"], mark, 0.0


def _entry(mode="be_then_trail", start=10, target=20, armed=None):
    return {
        "symbol": "DIA", "structure": "single",
        "legs": [{"broker_symbol": SYM, "qty": 5, "action": "BUY"}],
        "account_hashes": {"acct1": "HASH01"},
        "stop_mgmt": {"mode": mode, "start_pct": start, "trail_pct": 8, "target_pct": target,
                      "armed_hashes": armed or [], "arm_fails": {}},
    }


def test_evaluate_arms_when_profit_crosses_start():
    positions = {"DIA": _entry(start=10, target=20)}
    # mark 2.30 vs avg 2.00 = +15% ≥ start 10 and < target 20 → arm
    c = FakeClient(orders=[_oco_order("111", 2.40, 1.00)], positions=[_position(2.30)])
    n = trailing.evaluate_trailing_arms(
        active_positions=positions, make_client=lambda: c, avg_mark_fn=_avg_mark_fn,
        save_positions=lambda: None, now_utc=NOW, sleep=lambda s: None,
    )
    assert n == 1
    assert positions["DIA"]["stop_mgmt"]["armed_hashes"] == ["HASH01"]


def test_evaluate_skips_below_start():
    positions = {"DIA": _entry(start=10, target=20)}
    c = FakeClient(orders=[_oco_order("111", 2.40, 1.00)], positions=[_position(2.05)])  # +2.5%
    n = trailing.evaluate_trailing_arms(
        active_positions=positions, make_client=lambda: c, avg_mark_fn=_avg_mark_fn,
        save_positions=lambda: None, now_utc=NOW, sleep=lambda s: None,
    )
    assert n == 0 and positions["DIA"]["stop_mgmt"]["armed_hashes"] == []


def test_evaluate_idempotent_already_armed():
    positions = {"DIA": _entry(armed=["HASH01"])}
    c = FakeClient(orders=[_oco_order("111", 2.40, 1.00)], positions=[_position(2.30)])
    n = trailing.evaluate_trailing_arms(
        active_positions=positions, make_client=lambda: c, avg_mark_fn=_avg_mark_fn,
        save_positions=lambda: None, now_utc=NOW, sleep=lambda s: None,
    )
    assert n == 0 and c.place_calls == []  # already armed → no action


def test_evaluate_fixed_mode_never_arms():
    positions = {"DIA": _entry(mode="fixed")}
    c = FakeClient(orders=[_oco_order("111", 2.40, 1.00)], positions=[_position(2.30)])
    n = trailing.evaluate_trailing_arms(
        active_positions=positions, make_client=lambda: c, avg_mark_fn=_avg_mark_fn,
        save_positions=lambda: None, now_utc=NOW, sleep=lambda s: None,
    )
    assert n == 0


def test_evaluate_give_up_after_three_rejections():
    positions = {"DIA": _entry(start=10, target=20)}
    c = FakeClient(orders=[_oco_order("111", 2.40, 1.00)], positions=[_position(2.30)],
                   place_exc=Exception("order rejected: bad price"))
    for _ in range(3):
        trailing.evaluate_trailing_arms(
            active_positions=positions, make_client=lambda: c, avg_mark_fn=_avg_mark_fn,
            save_positions=lambda: None, now_utc=NOW, sleep=lambda s: None,
        )
    sm = positions["DIA"]["stop_mgmt"]
    assert sm["arm_fails"]["HASH01"] == 3
    assert "HASH01" in sm["armed_hashes"]  # gave up → stop hammering
