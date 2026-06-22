"""
================================================================================
File:          pnl_sync.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-15 12:21 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-15 12:21 EST

Purpose:
    Compute realized P&L for CLOSED option positions directly from Schwab
    /accounts/{hash}/transactions, so trades closed manually at Schwab (outside
    the dashboard's exit-send) still get captured.

    Method (robust + simple): net every OPTION trade leg by its contract symbol.
    When a contract's running signed quantity returns to 0, it is fully closed --
    realized P&L = the sum of that contract's cash flows (buys are debits, sells
    are credits). Each close carries a dedup_key (the contributing activity ids)
    so re-syncing never double-counts.

    Field mapping follows Schwab's documented transaction shape but is defensive
    (tries several key names) since the live JSON can vary; `parse_legs` returns
    the raw legs it found so the first real sync can be verified.

Change Log:
    2026-06-15 12:21 EST  v1.0.0  Initial implementation (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


@dataclass
class OptionLeg:
    activity_id: str
    option_symbol: str
    underlying: str
    quantity: float          # signed: + for buy (long), - for sell (short)
    cash: float              # signed cash impact: - for a buy (debit), + for a sell (credit)
    time: str = ""
    order_id: str = ""


def parse_legs(transactions: Iterable[dict]) -> list[OptionLeg]:
    """Extract OPTION trade legs from Schwab transactions, defensively."""
    legs: list[OptionLeg] = []
    for txn in transactions or []:
        if not isinstance(txn, dict):
            continue
        # TRADE = bought/sold legs. RECEIVE_AND_DELIVER = option expiration/assignment
        # (the contract leaving the account); including it lets an expired position net
        # to flat and realize its P&L, which Schwab's realized number also counts.
        if str(_first(txn, "type") or "").upper() not in ("", "TRADE", "RECEIVE_AND_DELIVER"):
            continue
        activity_id = str(_first(txn, "activityId", "transactionId") or "")
        order_id = str(_first(txn, "orderId") or "")
        when = str(_first(txn, "time", "tradeDate", "transactionDate", "settlementDate") or "")
        items = _first(txn, "transferItems", "transactionItems") or []
        for item in items if isinstance(items, list) else []:
            instrument = item.get("instrument", item) if isinstance(item, dict) else {}
            asset = str(_first(instrument, "assetType", "type") or "").upper()
            if "OPTION" not in asset:
                continue
            option_symbol = str(_first(instrument, "symbol") or "").strip()
            underlying = str(_first(instrument, "underlyingSymbol", "underlying") or "").strip()
            qty = _num(_first(item, "amount", "quantity"))
            price = _num(_first(item, "price"))
            cost = _num(_first(item, "cost", "netAmount", "amountTraded"))
            if qty is None:
                continue
            # Schwab signs `amount` (+ for a buy, - for a sell) and `cost`
            # (- for a debit/buy, + for a credit/sell) DIRECTLY, and those signs
            # are correct for BOTH long and short positions. Trust them.
            #
            # Do NOT infer direction from positionEffect: it only says
            # OPENING/CLOSING and cannot distinguish a long (buy-to-open) from a
            # short (sell-to-open) -- using it flips the cash sign on every short
            # (e.g. a sold-to-open call closed at a profit looked like a loss).
            signed_qty = qty  # already signed: +buy / -sell
            if cost is not None:
                # Expect cost's sign opposite to amount's (buy: +qty, -cash). If a
                # feed ever reports cost unsigned, re-derive the sign from amount.
                if (cost > 0 and qty > 0) or (cost < 0 and qty < 0):
                    signed_cash = -abs(cost) if qty > 0 else abs(cost)
                else:
                    signed_cash = cost
            elif price is not None:
                # buy (+qty) -> cash out (negative); sell (-qty) -> cash in (positive)
                signed_cash = -(qty * abs(price) * 100.0)
            else:
                signed_cash = 0.0
            legs.append(OptionLeg(
                activity_id=activity_id, option_symbol=option_symbol,
                underlying=underlying or _underlying_from_osym(option_symbol),
                quantity=signed_qty, cash=round(signed_cash, 2), time=when,
                order_id=order_id,
            ))
    return legs


def _underlying_from_osym(option_symbol: str) -> str:
    # OSI-style "QQQ   260615P00740000" -> "QQQ"
    return (option_symbol or "").strip().split(" ")[0][:6].strip()


@dataclass
class RealizedClose:
    underlying: str
    option_symbol: str
    contracts: int
    realized_pnl: float
    entry_price: float
    exit_price: float
    closed_at: str
    dedup_key: str
    order_ids: list = field(default_factory=list)
    leg_count: int = 0


def closes_from_transactions(transactions: Iterable[dict]) -> list[RealizedClose]:
    """Net OPTION legs per contract; emit a RealizedClose for each contract whose
    running quantity returns to flat (fully closed)."""
    legs = parse_legs(transactions)
    by_symbol: dict[str, list[OptionLeg]] = {}
    for leg in legs:
        by_symbol.setdefault(leg.option_symbol, []).append(leg)

    closes: list[RealizedClose] = []
    for option_symbol, sym_legs in by_symbol.items():
        net_qty = sum(l.quantity for l in sym_legs)
        if abs(net_qty) > 1e-9:
            continue  # still open -> not realized yet
        realized = round(sum(l.cash for l in sym_legs), 2)
        opens = [l for l in sym_legs if l.quantity > 0]
        sells = [l for l in sym_legs if l.quantity < 0]
        open_qty = sum(l.quantity for l in opens) or 1
        sell_qty = sum(-l.quantity for l in sells) or 1
        entry_price = round(sum(-l.cash for l in opens) / (open_qty * 100.0), 2)
        exit_price = round(sum(l.cash for l in sells) / (sell_qty * 100.0), 2)
        order_ids = sorted({l.order_id for l in sym_legs if l.order_id})
        # Prefer the Schwab order #s for the dedup key (stable across re-syncs and
        # reconcilable to the order history); fall back to activity ids if absent.
        key_ids = order_ids or sorted({l.activity_id for l in sym_legs if l.activity_id})
        # The dedup key MUST include the option symbol: a vertical spread's two legs
        # share the same order #s, so keying on order #s alone made the legs collide
        # and the second leg (usually the losing short leg) was dropped on record --
        # which overstated spread P&L. Keying per leg records BOTH legs.
        dedup_key = "schwab:" + option_symbol.replace(" ", "") + ":" + "|".join(key_ids)
        closes.append(RealizedClose(
            underlying=(sym_legs[0].underlying or _underlying_from_osym(option_symbol)).upper(),
            option_symbol=option_symbol,
            contracts=int(round(sum(l.quantity for l in opens))),
            realized_pnl=realized,
            entry_price=entry_price,
            exit_price=exit_price,
            closed_at=max((l.time for l in sym_legs if l.time), default=""),
            dedup_key=dedup_key,
            order_ids=order_ids,
            leg_count=len(sym_legs),
        ))
    return closes
