from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


ISO_FRACTION_RE = re.compile(r"(\.\d{6})\d+")
SIGNAL_ID_RE = re.compile(r"signal_id=([^;]+)")


def latest_telemetry_path(base_dir: Path | None = None) -> Path:
    root = base_dir or Path.cwd()
    files = sorted(root.glob("nt8_telemetry*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No nt8_telemetry*.csv files found in {root}")
    return files[0]


def load_telemetry_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def filter_rows_by_time(
    rows: list[dict[str, str]],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, str]]:
    filtered = []
    for row in rows:
        timestamp = parse_datetime(row.get("nt_bar_time"))
        if timestamp is None:
            continue
        comparable = timestamp.replace(tzinfo=None)
        if start is not None and comparable < start.replace(tzinfo=None):
            continue
        if end is not None and comparable > end.replace(tzinfo=None):
            continue
        filtered.append(row)
    return filtered


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    text = ISO_FRACTION_RE.sub(r"\1", text)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    parsed = parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def parse_day_start(value: str) -> time:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("day start must use HH:MM format") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("day start must use a valid HH:MM time")
    return time(hour, minute)


def extract_signal_id(notes: str | None) -> str:
    match = SIGNAL_ID_RE.search(notes or "")
    return match.group(1) if match else ""


def time_in_window(timestamp: datetime | None, start: time | None, end: time | None) -> bool:
    if timestamp is None or start is None or end is None:
        return True
    value = timestamp.time()
    if start == end:
        return True
    if start < end:
        return start <= value <= end
    return value >= start or value <= end


def session_date_for(timestamp: datetime | None, day_start: time) -> date | None:
    if timestamp is None:
        return None
    if day_start == time(0, 0):
        return timestamp.date()
    if timestamp.time() >= day_start:
        return timestamp.date() + timedelta(days=1)
    return timestamp.date()


def _money(value: float) -> float:
    return round(value, 2)


def _iso(timestamp: datetime | None) -> str | None:
    return timestamp.isoformat() if timestamp else None


def _empty_drawdown_point() -> dict[str, Any]:
    return {
        "amount": 0.0,
        "time": None,
        "equity": 0.0,
        "peak": 0.0,
        "trade_entry_time": None,
        "direction": None,
        "entry_price": None,
        "adverse_price": None,
    }


def _drawdown_point(
    amount: float,
    timestamp: datetime | None,
    equity: float,
    peak: float,
    trade: dict[str, Any] | None = None,
    adverse_price: float | None = None,
) -> dict[str, Any]:
    return {
        "amount": _money(amount),
        "time": _iso(timestamp),
        "equity": _money(equity),
        "peak": _money(peak),
        "trade_entry_time": _iso(trade.get("entry_time")) if trade else None,
        "direction": trade.get("direction") if trade else None,
        "entry_price": trade.get("entry_price") if trade else None,
        "adverse_price": adverse_price,
    }


def _blank_daily_state(session_date: str) -> dict[str, Any]:
    return {
        "session_date": session_date,
        "trades": 0,
        "targets": 0,
        "stops": 0,
        "ambiguous": 0,
        "unresolved": 0,
        "closed_pnl": 0.0,
        "closed_peak_pnl": 0.0,
        "closed_min_pnl": 0.0,
        "open_min_pnl": 0.0,
        "closed_max_drawdown": _empty_drawdown_point(),
        "open_equity_max_drawdown": _empty_drawdown_point(),
    }


def _ordered_rows(rows: list[dict[str, str]]) -> list[tuple[int, dict[str, str]]]:
    def key(item: tuple[int, dict[str, str]]) -> tuple[datetime, int, int]:
        index, row = item
        timestamp = parse_datetime(row.get("nt_bar_time")) or datetime.min
        bar_index = parse_int(row.get("bar_index")) or -1
        return (timestamp.replace(tzinfo=None), bar_index, index)

    return sorted(enumerate(rows), key=key)


def _adverse_unrealized_dollars(
    trade: dict[str, Any],
    row: dict[str, str],
    point_value: float,
    quantity: int,
) -> tuple[float, float] | None:
    entry_price = trade.get("entry_price")
    if entry_price is None:
        return None

    high = parse_float(row.get("high_price"))
    low = parse_float(row.get("low_price"))
    if high is None or low is None:
        return None

    direction = (trade.get("direction") or "").lower()
    stop_price = trade.get("stop_price")
    if direction == "long":
        adverse_price = low
        if stop_price is not None:
            adverse_price = max(adverse_price, stop_price)
        unrealized = (adverse_price - entry_price) * point_value * quantity
    elif direction == "short":
        adverse_price = high
        if stop_price is not None:
            adverse_price = min(adverse_price, stop_price)
        unrealized = (entry_price - adverse_price) * point_value * quantity
    else:
        return None

    return unrealized, adverse_price


def _max_adverse_for_trade(
    trade: dict[str, Any],
    bars: list[dict[str, str]],
    point_value: float,
    quantity: int,
) -> dict[str, Any]:
    entry_bar_index = trade.get("entry_bar_index")
    outcome_bar_index = trade.get("outcome_bar_index")
    if entry_bar_index is None or outcome_bar_index is None:
        return {"dollars": 0.0, "time": None, "price": None}

    worst_dollars = 0.0
    worst_time: datetime | None = None
    worst_price: float | None = None
    for row in bars:
        bar_index = parse_int(row.get("bar_index"))
        if bar_index is None or bar_index <= entry_bar_index or bar_index > outcome_bar_index:
            continue
        adverse = _adverse_unrealized_dollars(trade, row, point_value, quantity)
        if adverse is None:
            continue
        dollars, price = adverse
        if dollars < worst_dollars:
            worst_dollars = dollars
            worst_time = parse_datetime(row.get("nt_bar_time"))
            worst_price = price
    return {"dollars": _money(worst_dollars), "time": worst_time, "price": worst_price}


def build_trade_records(
    rows: list[dict[str, str]],
    *,
    point_value: float = 50.0,
    quantity: int = 1,
    source: str = "simulated",
) -> list[dict[str, Any]]:
    ordered = _ordered_rows(rows)
    bars = [row for _, row in ordered if row.get("event_type") == "bar"]
    pending_by_signal_id: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    for _, row in ordered:
        event_type = row.get("event_type", "")
        signal_id = extract_signal_id(row.get("notes"))
        if is_trade_entry_event(row, source):
            trade = {
                "signal_id": signal_id,
                "entry_time": parse_datetime(row.get("nt_bar_time")),
                "entry_bar_index": parse_int(row.get("bar_index")),
                "direction": row.get("direction", "").strip().lower(),
                "entry_price": parse_float(row.get("entry_price")) or parse_float(row.get("current_price")),
                "target_price": parse_float(row.get("target_price")),
                "stop_price": parse_float(row.get("stop_price")),
                "same_bar": (row.get("same_bar", "").strip().lower() == "true"),
                "arrow_bars_apart": parse_int(row.get("arrow_bars_apart")),
            }
            pending.append(trade)
            if signal_id:
                pending_by_signal_id[signal_id] = trade
            continue

        if not is_trade_outcome_event(row, source):
            continue

        trade = pending_by_signal_id.pop(signal_id, None) if signal_id else None
        if trade is None and pending:
            trade = pending.pop(0)
            if trade.get("signal_id"):
                pending_by_signal_id.pop(str(trade["signal_id"]), None)
        elif trade is not None and trade in pending:
            pending.remove(trade)
        if trade is None:
            trade = {
                "signal_id": signal_id,
                "entry_time": parse_datetime(row.get("nt_bar_time")),
                "entry_bar_index": parse_int(row.get("bar_index")),
                "direction": row.get("direction", "").strip().lower(),
                "entry_price": parse_float(row.get("entry_price")) or parse_float(row.get("current_price")),
                "target_price": parse_float(row.get("target_price")),
                "stop_price": parse_float(row.get("stop_price")),
                "same_bar": (row.get("same_bar", "").strip().lower() == "true"),
                "arrow_bars_apart": parse_int(row.get("arrow_bars_apart")),
            }

        trade["outcome_time"] = parse_datetime(row.get("nt_bar_time"))
        trade["outcome_bar_index"] = parse_int(row.get("bar_index"))
        trade["outcome"] = row.get("outcome", "").strip() or "unknown"
        trade["realized_dollars"] = parse_float(row.get("realized_dollars")) or 0.0
        adverse = _max_adverse_for_trade(trade, bars, point_value, quantity)
        trade["max_adverse_dollars"] = adverse["dollars"]
        trade["max_adverse_time"] = adverse["time"]
        trade["max_adverse_price"] = adverse["price"]
        trades.append(trade)

    return sorted(
        trades,
        key=lambda item: (
            (item.get("entry_time") or item.get("outcome_time") or datetime.min).replace(tzinfo=None),
            item.get("entry_bar_index") or -1,
        ),
    )


def is_trade_entry_event(row: dict[str, str], source: str = "simulated") -> bool:
    event_type = row.get("event_type", "")
    outcome = row.get("outcome", "").strip().lower()
    normalized = source.strip().lower()
    if normalized in {"nt", "ninjatrader", "actual"}:
        return event_type == "nt_execution" and outcome == "entry_fill"
    if normalized in {"simulated", "simulation", "dry_run", "dry-run"}:
        return event_type == "trade_opened"
    raise ValueError(f"Unsupported telemetry source: {source}")


def is_trade_outcome_event(row: dict[str, str], source: str = "simulated") -> bool:
    event_type = row.get("event_type", "")
    normalized = source.strip().lower()
    if normalized in {"nt", "ninjatrader", "actual"}:
        return event_type == "nt_trade_realized"
    if normalized in {"simulated", "simulation", "dry_run", "dry-run"}:
        return event_type == "trade_outcome"
    raise ValueError(f"Unsupported telemetry source: {source}")


def _session_state(session_date: str) -> dict[str, Any]:
    return {
        "session_date": session_date,
        "trades": 0,
        "skipped": 0,
        "targets": 0,
        "stops": 0,
        "pnl": 0.0,
        "peak": 0.0,
        "min": 0.0,
        "closed_max_drawdown": _empty_drawdown_point(),
        "open_equity_max_drawdown": _empty_drawdown_point(),
        "loss_streak": 0,
        "max_loss_streak": 0,
        "stopped_reason": None,
        "stopped_at": None,
        "failed_daily_drawdown": False,
    }


def simulate_trade_rules(
    trades: list[dict[str, Any]],
    *,
    day_start: time = time(18, 0),
    entry_start: time | None = None,
    entry_end: time | None = None,
    daily_profit_target: float | None = None,
    daily_loss_limit: float | None = None,
    daily_stop_limit: float | None = None,
    daily_drawdown_limit: float | None = None,
    max_consecutive_losses: int | None = None,
    max_trades_per_session: int | None = None,
    scenario_name: str = "scenario",
) -> dict[str, Any]:
    equity = 0.0
    peak = 0.0
    closed_max_drawdown = _empty_drawdown_point()
    open_equity_max_drawdown = _empty_drawdown_point()
    sessions: dict[str, dict[str, Any]] = {}
    skipped_reasons: Counter[str] = Counter()

    for trade in trades:
        entry_time = trade.get("entry_time") or trade.get("outcome_time")
        outcome_time = trade.get("outcome_time") or entry_time
        session_date = session_date_for(entry_time, day_start)
        if session_date is None:
            skipped_reasons["missing_time"] += 1
            continue
        key = session_date.isoformat()
        if key not in sessions:
            sessions[key] = _session_state(key)
        state = sessions[key]

        skip_reason = None
        if state["stopped_reason"]:
            skip_reason = f"session_stopped:{state['stopped_reason']}"
        elif not time_in_window(entry_time, entry_start, entry_end):
            skip_reason = "time_filter"
        elif daily_profit_target is not None and state["pnl"] >= daily_profit_target:
            skip_reason = "daily_profit_target"
        elif daily_loss_limit is not None and state["pnl"] <= -daily_loss_limit:
            skip_reason = "daily_loss_limit"
        elif max_trades_per_session is not None and state["trades"] >= max_trades_per_session:
            skip_reason = "max_trades_per_session"

        if skip_reason:
            state["skipped"] += 1
            skipped_reasons[skip_reason] += 1
            continue

        adverse = float(trade.get("max_adverse_dollars") or 0.0)
        open_equity = equity + adverse
        open_drawdown = peak - open_equity
        if open_drawdown > open_equity_max_drawdown["amount"]:
            open_equity_max_drawdown = _drawdown_point(
                open_drawdown,
                trade.get("max_adverse_time") or outcome_time,
                open_equity,
                peak,
                trade,
                trade.get("max_adverse_price"),
            )

        session_open_equity = state["pnl"] + adverse
        session_open_drawdown = state["peak"] - session_open_equity
        if session_open_drawdown > state["open_equity_max_drawdown"]["amount"]:
            state["open_equity_max_drawdown"] = _drawdown_point(
                session_open_drawdown,
                trade.get("max_adverse_time") or outcome_time,
                session_open_equity,
                state["peak"],
                trade,
                trade.get("max_adverse_price"),
            )
        state["min"] = min(state["min"], session_open_equity)
        if daily_drawdown_limit is not None and (
            session_open_drawdown >= daily_drawdown_limit or -session_open_equity >= daily_drawdown_limit
        ):
            state["failed_daily_drawdown"] = True

        pnl = float(trade.get("realized_dollars") or 0.0)
        equity += pnl
        if equity > peak:
            peak = equity
        closed_drawdown = peak - equity
        if closed_drawdown > closed_max_drawdown["amount"]:
            closed_max_drawdown = _drawdown_point(closed_drawdown, outcome_time, equity, peak, trade)
        if closed_drawdown > open_equity_max_drawdown["amount"]:
            open_equity_max_drawdown = _drawdown_point(closed_drawdown, outcome_time, equity, peak, trade)

        state["trades"] += 1
        outcome = trade.get("outcome")
        if outcome == "target":
            state["targets"] += 1
        elif outcome == "stop":
            state["stops"] += 1
        state["pnl"] += pnl
        if state["pnl"] > state["peak"]:
            state["peak"] = state["pnl"]
        state["min"] = min(state["min"], state["pnl"])
        session_closed_drawdown = state["peak"] - state["pnl"]
        if session_closed_drawdown > state["closed_max_drawdown"]["amount"]:
            state["closed_max_drawdown"] = _drawdown_point(session_closed_drawdown, outcome_time, state["pnl"], state["peak"], trade)
        if session_closed_drawdown > state["open_equity_max_drawdown"]["amount"]:
            state["open_equity_max_drawdown"] = _drawdown_point(session_closed_drawdown, outcome_time, state["pnl"], state["peak"], trade)

        if pnl < 0:
            state["loss_streak"] += 1
        elif pnl > 0:
            state["loss_streak"] = 0
        state["max_loss_streak"] = max(state["max_loss_streak"], state["loss_streak"])

        if daily_drawdown_limit is not None and (
            session_closed_drawdown >= daily_drawdown_limit or -state["pnl"] >= daily_drawdown_limit
        ):
            state["failed_daily_drawdown"] = True

        if daily_profit_target is not None and state["stopped_reason"] is None and state["pnl"] >= daily_profit_target:
            state["stopped_reason"] = "daily_profit_target"
            state["stopped_at"] = _iso(outcome_time)
        if daily_loss_limit is not None and state["stopped_reason"] is None and state["pnl"] <= -daily_loss_limit:
            state["stopped_reason"] = "daily_loss_limit"
            state["stopped_at"] = _iso(outcome_time)
        if daily_stop_limit is not None and state["stopped_reason"] is None and (
            session_closed_drawdown >= daily_stop_limit or -state["pnl"] >= daily_stop_limit
        ):
            state["stopped_reason"] = "daily_stop_limit"
            state["stopped_at"] = _iso(outcome_time)
        if (
            max_consecutive_losses is not None
            and state["stopped_reason"] is None
            and state["loss_streak"] >= max_consecutive_losses
        ):
            state["stopped_reason"] = "max_consecutive_losses"
            state["stopped_at"] = _iso(outcome_time)
        if (
            max_trades_per_session is not None
            and state["stopped_reason"] is None
            and state["trades"] >= max_trades_per_session
        ):
            state["stopped_reason"] = "max_trades_per_session"
            state["stopped_at"] = _iso(outcome_time)

    session_rows = []
    for state in sorted(sessions.values(), key=lambda item: item["session_date"]):
        row = {
            "session_date": state["session_date"],
            "trades": state["trades"],
            "skipped": state["skipped"],
            "targets": state["targets"],
            "stops": state["stops"],
            "pnl": _money(state["pnl"]),
            "closed_max_drawdown": state["closed_max_drawdown"],
            "open_equity_max_drawdown": state["open_equity_max_drawdown"],
            "loss_from_start": _money(max(0.0, -state["min"])),
            "max_loss_streak": state["max_loss_streak"],
            "stopped_reason": state["stopped_reason"],
            "stopped_at": state["stopped_at"],
            "failed_daily_drawdown": state["failed_daily_drawdown"],
        }
        session_rows.append(row)

    daily_failures = sum(1 for row in session_rows if row["failed_daily_drawdown"])
    return {
        "scenario": scenario_name,
        "input_trades": len(trades),
        "trades": sum(row["trades"] for row in session_rows),
        "skipped": sum(row["skipped"] for row in session_rows),
        "skipped_reasons": dict(skipped_reasons),
        "closed_net_pnl": _money(equity),
        "closed_max_drawdown": closed_max_drawdown,
        "open_equity_max_drawdown": open_equity_max_drawdown,
        "daily_failures": daily_failures,
        "sessions": session_rows,
        "settings": {
            "entry_start": entry_start.strftime("%H:%M") if entry_start else None,
            "entry_end": entry_end.strftime("%H:%M") if entry_end else None,
            "daily_profit_target": daily_profit_target,
            "daily_loss_limit": daily_loss_limit,
            "daily_stop_limit": daily_stop_limit,
            "daily_drawdown_limit": daily_drawdown_limit,
            "max_consecutive_losses": max_consecutive_losses,
            "max_trades_per_session": max_trades_per_session,
            "day_start": day_start.strftime("%H:%M"),
        },
    }


def analyze_telemetry_rows(
    rows: list[dict[str, str]],
    *,
    point_value: float = 50.0,
    quantity: int = 1,
    day_start: time = time(18, 0),
    daily_drawdown_limit: float | None = None,
    max_drawdown_limit: float | None = None,
    source: str = "simulated",
) -> dict[str, Any]:
    ordered = _ordered_rows(rows)
    event_counts = Counter(row.get("event_type", "") for _, row in ordered)

    closed_equity = 0.0
    closed_peak = 0.0
    closed_max_drawdown = _empty_drawdown_point()
    open_equity_max_drawdown = _empty_drawdown_point()

    open_trade: dict[str, Any] | None = None
    daily: dict[str, dict[str, Any]] = {}
    outcome_counts: Counter[str] = Counter()

    telemetry_times = [
        parsed
        for _, row in ordered
        if (parsed := parse_datetime(row.get("nt_bar_time"))) is not None
    ]
    capture_times = [
        parsed
        for _, row in ordered
        if (parsed := parse_datetime(row.get("captured_at_local"))) is not None
    ]

    def daily_state(timestamp: datetime | None) -> dict[str, Any] | None:
        session_date = session_date_for(timestamp, day_start)
        if session_date is None:
            return None
        key = session_date.isoformat()
        if key not in daily:
            daily[key] = _blank_daily_state(key)
        return daily[key]

    def update_open_drawdown(timestamp: datetime | None, equity: float, trade: dict[str, Any], adverse_price: float) -> None:
        nonlocal open_equity_max_drawdown
        global_drawdown = closed_peak - equity
        if global_drawdown > open_equity_max_drawdown["amount"]:
            open_equity_max_drawdown = _drawdown_point(global_drawdown, timestamp, equity, closed_peak, trade, adverse_price)

        state = daily_state(timestamp)
        if state is None:
            return
        session_equity = state["closed_pnl"] + (equity - closed_equity)
        state["open_min_pnl"] = min(state["open_min_pnl"], session_equity)
        daily_drawdown = state["closed_peak_pnl"] - session_equity
        if daily_drawdown > state["open_equity_max_drawdown"]["amount"]:
            state["open_equity_max_drawdown"] = _drawdown_point(
                daily_drawdown,
                timestamp,
                session_equity,
                state["closed_peak_pnl"],
                trade,
                adverse_price,
            )

    for _, row in ordered:
        event_type = row.get("event_type", "")
        timestamp = parse_datetime(row.get("nt_bar_time"))

        if is_trade_entry_event(row, source):
            open_trade = {
                "entry_time": timestamp,
                "entry_bar_index": parse_int(row.get("bar_index")),
                "entry_price": parse_float(row.get("entry_price")) or parse_float(row.get("current_price")),
                "direction": row.get("direction", "").strip().lower(),
                "stop_price": parse_float(row.get("stop_price")),
                "target_price": parse_float(row.get("target_price")),
            }
            continue

        if event_type == "bar" and open_trade is not None:
            bar_index = parse_int(row.get("bar_index"))
            entry_bar_index = open_trade.get("entry_bar_index")
            if bar_index is None or entry_bar_index is None or bar_index <= entry_bar_index:
                continue
            adverse = _adverse_unrealized_dollars(open_trade, row, point_value, quantity)
            if adverse is None:
                continue
            adverse_pnl, adverse_price = adverse
            update_open_drawdown(timestamp, closed_equity + adverse_pnl, open_trade, adverse_price)
            continue

        if not is_trade_outcome_event(row, source):
            continue

        pnl = parse_float(row.get("realized_dollars")) or 0.0
        closed_equity += pnl
        outcome = row.get("outcome", "").strip() or "unknown"
        outcome_counts[outcome] += 1

        if closed_equity > closed_peak:
            closed_peak = closed_equity
        closed_drawdown = closed_peak - closed_equity
        if closed_drawdown > closed_max_drawdown["amount"]:
            closed_max_drawdown = _drawdown_point(closed_drawdown, timestamp, closed_equity, closed_peak, open_trade)
        if closed_drawdown > open_equity_max_drawdown["amount"]:
            open_equity_max_drawdown = _drawdown_point(closed_drawdown, timestamp, closed_equity, closed_peak, open_trade)

        state = daily_state(timestamp)
        if state is not None:
            state["trades"] += 1
            outcome_key = {
                "target": "targets",
                "stop": "stops",
                "ambiguous": "ambiguous",
                "unresolved": "unresolved",
            }.get(outcome)
            if outcome_key:
                state[outcome_key] += 1
            state["closed_pnl"] += pnl
            if state["closed_pnl"] > state["closed_peak_pnl"]:
                state["closed_peak_pnl"] = state["closed_pnl"]
            if state["closed_pnl"] < state["closed_min_pnl"]:
                state["closed_min_pnl"] = state["closed_pnl"]
            if state["closed_pnl"] < state["open_min_pnl"]:
                state["open_min_pnl"] = state["closed_pnl"]

            daily_closed_drawdown = state["closed_peak_pnl"] - state["closed_pnl"]
            if daily_closed_drawdown > state["closed_max_drawdown"]["amount"]:
                state["closed_max_drawdown"] = _drawdown_point(
                    daily_closed_drawdown,
                    timestamp,
                    state["closed_pnl"],
                    state["closed_peak_pnl"],
                    open_trade,
                )
            if daily_closed_drawdown > state["open_equity_max_drawdown"]["amount"]:
                state["open_equity_max_drawdown"] = _drawdown_point(
                    daily_closed_drawdown,
                    timestamp,
                    state["closed_pnl"],
                    state["closed_peak_pnl"],
                    open_trade,
                )

        open_trade = None

    daily_rows = []
    for state in daily.values():
        closed_loss_from_start = max(0.0, -state["closed_min_pnl"])
        open_loss_from_start = max(0.0, -state["open_min_pnl"])
        row = {
            "session_date": state["session_date"],
            "trades": state["trades"],
            "targets": state["targets"],
            "stops": state["stops"],
            "ambiguous": state["ambiguous"],
            "unresolved": state["unresolved"],
            "closed_pnl": _money(state["closed_pnl"]),
            "closed_loss_from_start": _money(closed_loss_from_start),
            "open_loss_from_start": _money(open_loss_from_start),
            "closed_max_drawdown": state["closed_max_drawdown"],
            "open_equity_max_drawdown": state["open_equity_max_drawdown"],
        }
        if daily_drawdown_limit is not None:
            row["daily_drawdown_limit"] = daily_drawdown_limit
            row["would_fail_daily_drawdown"] = (
                row["open_equity_max_drawdown"]["amount"] >= daily_drawdown_limit
                or row["open_loss_from_start"] >= daily_drawdown_limit
            )
        daily_rows.append(row)

    daily_rows.sort(key=lambda item: item["session_date"])
    trade_times = [
        parse_datetime(row.get("nt_bar_time"))
        for _, row in ordered
        if is_trade_entry_event(row, source) or is_trade_outcome_event(row, source)
    ]
    trade_times = [timestamp for timestamp in trade_times if timestamp is not None]

    summary: dict[str, Any] = {
        "row_count": len(rows),
        "event_counts": dict(event_counts),
        "outcome_counts": dict(outcome_counts),
        "trade_outcomes": sum(outcome_counts.values()),
        "closed_net_pnl": _money(closed_equity),
        "closed_max_drawdown": closed_max_drawdown,
        "open_equity_max_drawdown": open_equity_max_drawdown,
        "daily": daily_rows,
        "telemetry_start": _iso(min(telemetry_times)) if telemetry_times else None,
        "telemetry_end": _iso(max(telemetry_times)) if telemetry_times else None,
        "capture_start": _iso(min(capture_times)) if capture_times else None,
        "capture_end": _iso(max(capture_times)) if capture_times else None,
        "trade_start": _iso(min(trade_times)) if trade_times else None,
        "trade_end": _iso(max(trade_times)) if trade_times else None,
        "day_start": day_start.strftime("%H:%M"),
        "point_value": point_value,
        "quantity": quantity,
        "trade_source": source,
    }
    if max_drawdown_limit is not None:
        summary["max_drawdown_limit"] = max_drawdown_limit
        summary["would_fail_max_drawdown"] = open_equity_max_drawdown["amount"] >= max_drawdown_limit
    return summary
