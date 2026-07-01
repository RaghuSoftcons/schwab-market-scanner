# ============================================================================
# File:          trailing.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
# Version:       1.0.0
# Last Modified: 2026-07-01 (EST)
# Purpose:       Active trailing-stop management (single-leg), ported from the
#                Unified nt-bridge-v2 trailing monitor. A bridge-sent OTOCO
#                position rests as OCO[target LIMIT, fixed STOP]. Once the position
#                crosses +start_pct profit this ARMS the account: cancel the resting
#                OCO and place a new OCO whose stop is a breakeven STOP and/or a
#                native TRAILING_STOP. Idempotent per account (armed_hashes);
#                transient failures retry, genuine Schwab rejections give up after 3.
#
# Change Log:
#   2026-07-01  v1.0.0  Initial port from nt-bridge-v2 (Claude + Raghu).
# ============================================================================
"""Active stop management (breakeven / trailing) for scanner-sent single-leg positions.

Pure of app/framework state: every dependency (Schwab client, position-normalizer,
persistence, clock, logger) is injected so the whole module is unit-testable without a
live broker. `evaluate_trailing_arms()` is the one entry point the background loop calls.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional


# ---- error taxonomy ---------------------------------------------------------
# A genuine Schwab rejection (bad price, closed market, insufficient shares) is PERMANENT and
# counts toward a 3-strike give-up. A transient failure (auth expiry, network, 5xx) must NOT —
# it retries next cycle. Getting this wrong is exactly the bug that cost the Unified bridge a
# whole day of un-armed trails, so keep the marker list conservative (transient by exception).
_TRANSIENT_ARM_MARKERS = (
    "timeout", "timed out", "connection", "connection reset", "temporarily",
    "handshake", "ssl", "401", "403", "429", "500", "502", "503", "504",
    "expired", "unauthorized", "rate limit", "gateway", "unavailable",
)


class _TrailArmRejected(Exception):
    """Raised only when Schwab GENUINELY rejects the armed order (permanent → give-up)."""


def is_transient_arm_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_ARM_MARKERS)


# ---- symbol helpers ---------------------------------------------------------
def osi_underlying(broker_symbol: str) -> str:
    """Root ticker from an OSI option symbol ('DIA   260702C00523000' -> 'DIA')."""
    core = (broker_symbol or "").strip()
    if len(core) > 15:
        return core[:-15].strip().upper()
    return core.upper()


def _exit_legs(broker_symbol: str, qty: int) -> list[dict]:
    # A bridge single-leg entry is BUY_TO_OPEN, so the close is SELL_TO_CLOSE.
    return [
        {
            "instruction": "SELL_TO_CLOSE",
            "quantity": qty,
            "instrument": {"symbol": broker_symbol, "assetType": "OPTION"},
        }
    ]


# ---- stop-child payload builders (match _schwab_single_option_oco_exit_payload) ----
def breakeven_stop_payload(broker_symbol: str, qty: int, entry_price: float) -> dict:
    """Plain STOP at the entry price — once armed, the trade can't give back below breakeven."""
    return {
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "STOP",
        "complexOrderStrategyType": "NONE",
        "quantity": qty,
        "stopPrice": f"{round(entry_price, 2):.2f}",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": _exit_legs(broker_symbol, qty),
    }


def trailing_stop_payload(broker_symbol: str, qty: int, trail_distance_percent: float, entry_price: float) -> dict:
    """Native Schwab TRAILING_STOP: a MARK-linked dollar offset = entry * trail%/100."""
    offset = round(entry_price * (float(trail_distance_percent) / 100.0), 2)
    if offset <= 0:
        offset = 0.01
    return {
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "TRAILING_STOP",
        "complexOrderStrategyType": "NONE",
        "quantity": qty,
        "stopPriceLinkBasis": "MARK",
        "stopPriceLinkType": "VALUE",
        "stopPriceOffset": offset,
        "orderStrategyType": "SINGLE",
        "orderLegCollection": _exit_legs(broker_symbol, qty),
    }


def stop_replacement_payload(
    stop_mode: str, broker_symbol: str, qty: int, entry_price: float, trail_distance_percent: float
) -> Optional[dict]:
    """The order that REPLACES the fixed stop when arming. None for 'fixed' (no change)."""
    if stop_mode == "fixed":
        return None
    if stop_mode == "breakeven":
        return breakeven_stop_payload(broker_symbol, qty, entry_price)
    if stop_mode in ("trailing", "be_then_trail"):
        # be_then_trail arms straight to a trailing stop whose floor is already >= entry once the
        # position is up start_pct (the trail can only move the stop up from there).
        return trailing_stop_payload(broker_symbol, qty, trail_distance_percent, entry_price)
    return None


def _target_limit_child(broker_symbol: str, qty: int, target_limit_price: float) -> dict:
    return {
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "LIMIT",
        "complexOrderStrategyType": "NONE",
        "quantity": qty,
        "price": f"{round(target_limit_price, 2):.2f}",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": _exit_legs(broker_symbol, qty),
    }


def build_arm_oco_payload(
    stop_mgmt: dict, broker_symbol: str, qty: int, entry_avg: float, target_limit_price: float
) -> Optional[dict]:
    """The OCO that replaces the resting fixed-stop bracket. None for 'fixed' mode."""
    stop_child = stop_replacement_payload(
        str(stop_mgmt.get("mode") or "fixed"), broker_symbol, qty, entry_avg,
        float(stop_mgmt.get("trail_pct") or 0),
    )
    if stop_child is None:
        return None
    return {
        "orderStrategyType": "OCO",
        "childOrderStrategies": [
            _target_limit_child(broker_symbol, qty, target_limit_price),
            stop_child,
        ],
    }


def build_fixed_oco_payload(broker_symbol: str, qty: int, target_limit_price: float, stop_price: float) -> dict:
    """Rebuild the ORIGINAL fixed-stop OCO — used to RESTORE protection if the armed place fails."""
    return {
        "orderStrategyType": "OCO",
        "childOrderStrategies": [
            _target_limit_child(broker_symbol, qty, target_limit_price),
            {
                "session": "NORMAL",
                "duration": "GOOD_TILL_CANCEL",
                "orderType": "STOP",
                "complexOrderStrategyType": "NONE",
                "quantity": qty,
                "stopPrice": f"{round(stop_price, 2):.2f}",
                "orderStrategyType": "SINGLE",
                "orderLegCollection": _exit_legs(broker_symbol, qty),
            },
        ],
    }


# ---- resting-order discovery ------------------------------------------------
_OPEN_STATUSES = {
    "WORKING", "ACCEPTED", "QUEUED", "PENDING_ACTIVATION", "AWAITING_PARENT_ORDER",
    "AWAITING_CONDITION", "AWAITING_MANUAL_REVIEW", "PENDING_RECALL",
}


def _leg_matches(order: dict, osi_symbol: str) -> bool:
    for leg in order.get("orderLegCollection") or []:
        inst = leg.get("instrument") if isinstance(leg.get("instrument"), dict) else {}
        if str((inst or {}).get("symbol", "")).strip() == osi_symbol.strip():
            return True
    return False


def _price(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resting_oco_for_symbol(orders: list[dict], osi_symbol: str) -> Optional[dict]:
    """Find the WORKING OCO bracket (target LIMIT + STOP) on a symbol, at any nesting level.

    Returns {'cancel_id', 'limit', 'stop', 'qty'} for the OCO to cancel, or None. Handles both a
    top-level OCO and an OCO that is still nested under a partially/only-just-filled OTOCO trigger.
    """
    found: Optional[dict] = None

    def scan(order: dict) -> None:
        nonlocal found
        if found is not None or not isinstance(order, dict):
            return
        if str(order.get("orderStrategyType", "")) == "OCO":
            children = order.get("childOrderStrategies") or []
            limit_px = stop_px = qty = None
            symbol_seen = False
            for child in children:
                if not isinstance(child, dict):
                    continue
                if _leg_matches(child, osi_symbol):
                    symbol_seen = True
                ot = str(child.get("orderType", ""))
                if ot == "LIMIT":
                    limit_px = _price(child.get("price"))
                elif ot in ("STOP", "STOP_LIMIT", "TRAILING_STOP"):
                    stop_px = _price(child.get("stopPrice"))
                for leg in child.get("orderLegCollection") or []:
                    qv = _price(leg.get("quantity"))
                    if qv:
                        qty = int(qv)
            status = str(order.get("status", "")).upper()
            if symbol_seen and (status in _OPEN_STATUSES or not status):
                found = {
                    "cancel_id": str(order.get("orderId") or ""),
                    "limit": limit_px,
                    "stop": stop_px,
                    "qty": qty,
                }
                return
        for child in order.get("childOrderStrategies") or []:
            scan(child)

    for o in orders or []:
        scan(o)
        if found is not None:
            break
    return found if (found and found.get("cancel_id")) else None


def confirm_orders_cleared(
    client, account_hash: str, order_ids: list[str], frm: str, to: str,
    *, timeout_s: float = 2.0, step_s: float = 0.3, sleep: Callable[[float], None] = time.sleep
) -> bool:
    """Poll the order book until the cancelled ids leave it (avoids a cancel/place race)."""
    targets = {str(i) for i in order_ids if i}
    if not targets:
        return True
    deadline = timeout_s
    elapsed = 0.0
    while elapsed <= deadline:
        try:
            orders = client.get_orders(account_hash, frm, to)
        except Exception:
            return False
        still_open = set()

        def scan(order: dict) -> None:
            if not isinstance(order, dict):
                return
            oid = str(order.get("orderId") or "")
            status = str(order.get("status", "")).upper()
            if oid in targets and status in _OPEN_STATUSES:
                still_open.add(oid)
            for child in order.get("childOrderStrategies") or []:
                scan(child)

        for o in orders or []:
            scan(o)
        if not still_open:
            return True
        sleep(step_s)
        elapsed += step_s
    return False


# ---- per-account arm --------------------------------------------------------
def arm_account_stop(
    *, client, account_hash: str, broker_symbol: str, qty: int, entry_avg: float,
    stop_mgmt: dict, frm: str, to: str, log: Optional[Callable[[str], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[str]:
    """Arm one account: cancel the resting fixed-stop OCO, place the armed (BE/trailing) OCO.

    Returns the new broker order id on success; None on a transient failure (retry next cycle);
    raises _TrailArmRejected on a genuine Schwab rejection (counts toward give-up).
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    # 1) locate the resting OCO to replace
    try:
        orders = client.get_orders(account_hash, frm, to)
    except Exception as exc:
        if is_transient_arm_error(exc):
            return None
        raise _TrailArmRejected(f"get_orders failed: {exc}") from exc

    resting = resting_oco_for_symbol(orders, broker_symbol)
    if not resting:
        # No bracket to replace (already armed elsewhere, or target/stop already fired). Skip.
        return None

    use_qty = int(resting.get("qty") or qty or 0)
    target_limit = resting.get("limit")
    if use_qty <= 0 or target_limit is None:
        return None
    original_stop = resting.get("stop")

    armed = build_arm_oco_payload(stop_mgmt, broker_symbol, use_qty, entry_avg, float(target_limit))
    if armed is None:
        return None  # fixed mode — nothing to arm

    cancel_id = resting["cancel_id"]

    # 2) cancel the resting OCO
    try:
        client.cancel_order(account_hash, cancel_id)
    except Exception as exc:
        if is_transient_arm_error(exc):
            return None
        raise _TrailArmRejected(f"cancel failed: {exc}") from exc

    # 3) best-effort confirm it left the book before we place the replacement
    confirm_orders_cleared(client, account_hash, [cancel_id], frm, to, sleep=sleep)

    # 4) place the armed OCO
    try:
        result = client.place_order(account_hash, armed)
    except Exception as exc:
        # the fixed stop is already cancelled — try to RESTORE protection so we never sit naked
        _log(f"armed place failed for {broker_symbol} on {account_hash[:6]}…: {exc}; restoring fixed OCO")
        if original_stop is not None:
            try:
                client.place_order(
                    account_hash,
                    build_fixed_oco_payload(broker_symbol, use_qty, float(target_limit), float(original_stop)),
                )
            except Exception:
                pass  # restore is best-effort; the retry next cycle will re-attempt the arm
        if is_transient_arm_error(exc):
            return None
        raise _TrailArmRejected(f"place failed: {exc}") from exc

    new_id = ""
    if isinstance(result, dict):
        new_id = str(result.get("broker_order_id") or result.get("orderId") or "")
    _log(f"armed {stop_mgmt.get('mode')} stop for {broker_symbol} on {account_hash[:6]}… (order {new_id})")
    return new_id or "armed"


# ---- monitor entry point ----------------------------------------------------
def evaluate_trailing_arms(
    *, active_positions: dict, make_client: Callable[[], Any],
    avg_mark_fn: Callable[[dict], tuple], save_positions: Callable[[], None],
    now_utc, log: Optional[Callable[[str], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """One monitor cycle. Returns the count of accounts newly armed this pass.

    For every single-leg tracked position whose stop_mgmt.mode is not fixed, for every account
    not yet armed: read the live position, and once profit% >= start_pct (and start_pct is below
    the first target so we don't arm past it), arm that account.
    """
    from datetime import timedelta

    def _log(msg: str) -> None:
        if log:
            log(msg)

    frm = (now_utc - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to = now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    newly_armed = 0
    dirty = False

    for entry in list(active_positions.values()):
        if not isinstance(entry, dict):
            continue
        sm = entry.get("stop_mgmt")
        if not isinstance(sm, dict):
            continue
        mode = str(sm.get("mode") or "fixed")
        if mode == "fixed":
            continue
        legs = entry.get("legs") or []
        if len(legs) != 1:
            continue  # single-leg only
        broker_symbol = str((legs[0] or {}).get("broker_symbol") or "").strip()
        if not broker_symbol:
            continue

        start_pct = float(sm.get("start_pct") or 0)
        target_pct = float(sm.get("target_pct") or 0)
        if target_pct and start_pct >= target_pct:
            continue  # start must be below the first target, else we'd arm past the exit

        armed_hashes = sm.setdefault("armed_hashes", [])
        arm_fails = sm.setdefault("arm_fails", {})
        account_hashes = entry.get("account_hashes") or {}
        # account_hashes is {account_id: hash}; iterate the hash values
        hashes = [h for h in account_hashes.values() if h] if isinstance(account_hashes, dict) else list(account_hashes)

        client = None
        for account_hash in hashes:
            if account_hash in armed_hashes:
                continue
            if client is None:
                client = make_client()
            # read the live position for this contract on this account
            try:
                positions = client.get_positions(account_hash)
            except Exception as exc:
                _log(f"positions read failed on {account_hash[:6]}…: {exc}")
                continue
            raw = None
            for p in positions or []:
                inst = p.get("instrument") if isinstance(p.get("instrument"), dict) else {}
                if str((inst or {}).get("symbol", "")).strip() == broker_symbol:
                    raw = p
                    break
            if raw is None:
                continue  # not held on this account (closed) — nothing to arm
            avg, mark, _ = avg_mark_fn(raw)
            if not avg or not mark or avg <= 0:
                continue
            profit_pct = (mark - avg) / avg * 100.0
            if profit_pct < start_pct:
                continue  # not far enough in profit yet
            if target_pct and start_pct >= target_pct:
                continue

            try:
                order_id = arm_account_stop(
                    client=client, account_hash=account_hash, broker_symbol=broker_symbol,
                    qty=int((legs[0] or {}).get("qty") or 0), entry_avg=float(avg),
                    stop_mgmt=sm, frm=frm, to=to, log=log, sleep=sleep,
                )
            except _TrailArmRejected as exc:
                arm_fails[account_hash] = int(arm_fails.get(account_hash, 0)) + 1
                _log(f"arm rejected ({arm_fails[account_hash]}/3) {broker_symbol} on {account_hash[:6]}…: {exc}")
                if arm_fails[account_hash] >= 3:
                    armed_hashes.append(account_hash)  # give up so we stop hammering Schwab
                    dirty = True
                continue
            if order_id:
                armed_hashes.append(account_hash)
                newly_armed += 1
                dirty = True

    if dirty:
        try:
            save_positions()
        except Exception:
            pass
    return newly_armed
