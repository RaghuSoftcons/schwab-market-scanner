from nt_schwab_bridge.pnl_sync import closes_from_transactions, parse_legs


def _rad(aid, sym, amount, cost, when="2026-06-15T20:00:00+0000"):
    """RECEIVE_AND_DELIVER txn: an option expiration/assignment (contract leaving the
    account). amount/cost signed as Schwab reports (cost 0 for a worthless expiry)."""
    return {
        "activityId": aid, "type": "RECEIVE_AND_DELIVER", "time": when,
        "transferItems": [{
            "instrument": {"assetType": "OPTION", "symbol": sym, "underlyingSymbol": sym.split()[0]},
            "amount": amount, "cost": cost,
        }],
    }


def _txn(aid, sym, amount, price, cost, when="2026-06-15T13:00:00+0000", order_id=None,
         effect="OPENING"):
    """Build a Schwab-shaped TRADE txn. `amount` and `cost` are SIGNED exactly as
    Schwab reports them: amount +buy/-sell, cost -debit(buy)/+credit(sell).
    `effect` (OPENING/CLOSING) is intentionally arbitrary -- the parser must NOT
    rely on it (that was the short-position sign bug)."""
    return {
        "activityId": aid, "type": "TRADE", "time": when, "orderId": order_id,
        "transferItems": [{
            "instrument": {"assetType": "OPTION", "symbol": sym, "underlyingSymbol": sym.split()[0]},
            "amount": amount, "price": price, "cost": cost, "positionEffect": effect,
        }],
    }


def test_single_put_roundtrip_91_profit_with_order_ids():
    # Long put: buy to open (+1, -310), sell to close (-1, +401) -> +91.
    txns = [
        _txn(1, "QQQ 260615P00740000", 1, 3.10, -310, order_id="100", effect="OPENING"),
        _txn(2, "QQQ 260615P00740000", -1, 4.01, 401, "2026-06-15T13:45:00+0000", order_id="200", effect="CLOSING"),
    ]
    closes = closes_from_transactions(txns)
    assert len(closes) == 1
    c = closes[0]
    assert c.underlying == "QQQ"
    assert c.contracts == 1
    assert c.realized_pnl == 91.0          # -310 + 401
    assert c.order_ids == ["100", "200"]   # both order #s captured
    assert c.dedup_key == "schwab:QQQ260615P00740000:100|200"  # keyed per leg + order #s


def test_spread_legs_get_distinct_keys_and_both_record():
    # A vertical's two legs share the same OPEN/CLOSE order #s. Keys must differ by
    # option symbol so BOTH legs record (previously the short leg was dropped).
    txns = [
        _txn(1, "MU 260626C01035000", 1, 5.0, -500, order_id="OPEN", effect="OPENING"),
        _txn(2, "MU 260626C01040000", -1, 3.0, 300, order_id="OPEN", effect="OPENING"),
        _txn(3, "MU 260626C01035000", -1, 8.0, 800, order_id="CLOSE", effect="CLOSING"),
        _txn(4, "MU 260626C01040000", 1, 5.0, -500, order_id="CLOSE", effect="CLOSING"),
    ]
    closes = closes_from_transactions(txns)
    assert len(closes) == 2
    keys = {c.dedup_key for c in closes}
    assert len(keys) == 2, "spread legs must have distinct dedup keys"
    # long leg +300, short leg -200 -> spread net +100 (paid 2.00 debit, closed 3.00)
    assert round(sum(c.realized_pnl for c in closes), 2) == 100.0


def test_short_call_roundtrip_profit_not_inverted():
    # SHORT call: sell to open (-1, +300 credit), buy to close (+1, -100 debit) -> +200.
    # The OLD positionEffect logic flipped this to a loss; guard against regression.
    txns = [
        _txn(1, "SPY 260615C00750000", -1, 3.00, 300, order_id="10", effect="OPENING"),
        _txn(2, "SPY 260615C00750000", 1, 1.00, -100, "2026-06-15T14:00:00+0000", order_id="20", effect="CLOSING"),
    ]
    c = closes_from_transactions(txns)[0]
    assert c.realized_pnl == 200.0         # +300 - 100, a real profit (not -200)
    assert c.contracts == 1


def test_dedup_falls_back_to_activity_id_when_no_order_id():
    txns = [
        _txn(1, "QQQ 260615P00740000", 1, 3.10, -310),
        _txn(2, "QQQ 260615P00740000", -1, 4.01, 401),
    ]
    c = closes_from_transactions(txns)[0]
    assert c.order_ids == []
    assert c.dedup_key == "schwab:QQQ260615P00740000:1|2"


def test_open_only_is_not_realized():
    txns = [_txn(1, "SPY 260616C00744000", 1, 2.06, -206)]
    assert closes_from_transactions(txns) == []


def test_long_expired_worthless_via_receive_and_deliver_realizes_debit():
    # Long put bought for $310; expires worthless (RECEIVE_AND_DELIVER removes it at $0).
    txns = [
        _txn(1, "QQQ 260615P00740000", 1, 3.10, -310, order_id="OPEN"),
        _rad(2, "QQQ 260615P00740000", -1, 0.0),
    ]
    c = closes_from_transactions(txns)[0]
    assert c.realized_pnl == -310.0   # full debit lost


def test_short_expired_worthless_via_receive_and_deliver_keeps_credit():
    # Sold a call for $300; expires worthless -> keep the full +300 credit.
    txns = [
        _txn(1, "SPY 260615C00750000", -1, 3.00, 300, order_id="OPEN"),
        _rad(2, "SPY 260615C00750000", 1, 0.0),
    ]
    c = closes_from_transactions(txns)[0]
    assert c.realized_pnl == 300.0


def test_loss_roundtrip():
    # Long call x2: buy to open (+2, -300), sell to close (-2, +200) -> -100.
    txns = [
        _txn(1, "DIA 260618C00520000", 2, 1.50, -300),
        _txn(2, "DIA 260618C00520000", -2, 1.00, 200),
    ]
    c = closes_from_transactions(txns)[0]
    assert c.realized_pnl == -100.0        # -300 + 200
    assert c.contracts == 2
