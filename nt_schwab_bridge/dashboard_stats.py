"""
================================================================================
File:          dashboard_stats.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 15:00 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 15:00 EST

Purpose:
    Backend data layer for the dashboard enhancements (brief Step 7). Computes
    the numbers the new dashboard panels need, from closed-trade events:
      - Real-time P&L: today / this week / this month / all-time
      - Equity curve: cumulative P&L points over time
      - Win-rate summary per indicator and per symbol (via PerformanceTracker)
      - System health: token status + per-service reachability + quote freshness
    This is pure data; the UI rendering is a separate, incremental pass so the
    existing dashboard is never broken in one big change.

Change Log:
    2026-06-13 15:00 EST  v1.0.0  Initial implementation (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

UTC = timezone.utc


@dataclass
class TradeClose:
    """A realized close event used to compute P&L and the equity curve."""

    closed_at: datetime
    symbol: str
    indicator: str
    account_id: str
    realized_pnl: float
    won: bool


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class PnlSummary:
    today: float = 0.0
    week: float = 0.0
    month: float = 0.0
    all_time: float = 0.0
    trade_count: int = 0
    wins: int = 0
    losses: int = 0

    @property
    def win_rate(self) -> Optional[float]:
        total = self.wins + self.losses
        return None if total == 0 else round(self.wins / total, 4)

    def as_dict(self) -> dict:
        return {
            "today": round(self.today, 2),
            "week": round(self.week, 2),
            "month": round(self.month, 2),
            "all_time": round(self.all_time, 2),
            "trade_count": self.trade_count,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
        }


def compute_pnl(closes: Iterable[TradeClose], *, now: datetime | None = None) -> PnlSummary:
    """Aggregate realized P&L over today / week / month / all-time windows."""

    now = _as_utc(now or datetime.now(UTC))
    today = now.date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    month_start = today.replace(day=1)

    s = PnlSummary()
    for c in closes:
        when = _as_utc(c.closed_at).date()
        s.all_time += c.realized_pnl
        s.trade_count += 1
        if c.won:
            s.wins += 1
        else:
            s.losses += 1
        if when == today:
            s.today += c.realized_pnl
        if when >= week_start:
            s.week += c.realized_pnl
        if when >= month_start:
            s.month += c.realized_pnl
    return s


def equity_curve(closes: Iterable[TradeClose]) -> list[dict]:
    """Cumulative P&L points (sorted by close time) for the equity-curve chart."""

    ordered = sorted(closes, key=lambda c: _as_utc(c.closed_at))
    cumulative = 0.0
    points: list[dict] = []
    for c in ordered:
        cumulative += c.realized_pnl
        points.append(
            {
                "at": _as_utc(c.closed_at).isoformat(),
                "symbol": c.symbol,
                "pnl": round(c.realized_pnl, 2),
                "cumulative": round(cumulative, 2),
            }
        )
    return points


def trade_history(
    closes: Iterable[TradeClose],
    *,
    symbol: str | None = None,
    indicator: str | None = None,
    account_id: str | None = None,
    result: str | None = None,  # "win" | "loss" | None
) -> list[dict]:
    """Filtered trade-history rows for the dashboard table."""

    rows: list[dict] = []
    for c in closes:
        if symbol and c.symbol.upper() != symbol.upper():
            continue
        if indicator and c.indicator != indicator:
            continue
        if account_id and c.account_id != account_id:
            continue
        if result == "win" and not c.won:
            continue
        if result == "loss" and c.won:
            continue
        rows.append(
            {
                "closed_at": _as_utc(c.closed_at).isoformat(),
                "symbol": c.symbol,
                "indicator": c.indicator,
                "account_id": c.account_id,
                "pnl": round(c.realized_pnl, 2),
                "result": "win" if c.won else "loss",
            }
        )
    rows.sort(key=lambda r: r["closed_at"], reverse=True)
    return rows


def token_status_from_file(path: str | None) -> tuple[str, bool]:
    """Read token status straight from the shared token file (no deps).

    Returns (status, read_only) where status is one of
    valid | expiring | expired | login_required | unknown. read_only is True
    for expired / login_required / unknown so callers can fall back to a
    market-data-only posture (graceful degradation).
    """

    import json
    from pathlib import Path

    if not path:
        return "unknown", True
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return "unknown", True

    access = str(data.get("access_token", "")).strip()
    if not access:
        return "expired", True
    if data.get("login_required"):
        return "login_required", True
    try:
        parsed = datetime.fromisoformat(str(data.get("access_token_expires_at")))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        seconds = (parsed - datetime.now(UTC)).total_seconds()
        if seconds <= 0:
            return "expired", True
        if seconds <= 300:
            return "expiring", False
        return "valid", False
    except (TypeError, ValueError):
        return "unknown", True


def pnl_by_account(closes: Iterable[TradeClose], *, now: datetime | None = None) -> list[dict]:
    """Per-account realized P&L (today / week / all-time) + win/loss, so the dashboard
    can expand the combined headline into one row per funded account."""

    now = _as_utc(now or datetime.now(UTC))
    today = now.date()
    week_start = today - timedelta(days=today.weekday())  # Monday

    groups: dict[str, dict] = {}
    for c in closes:
        acct = c.account_id or "(unknown)"
        g = groups.setdefault(
            acct,
            {"account_id": acct, "today": 0.0, "week": 0.0, "all_time": 0.0,
             "wins": 0, "losses": 0, "trade_count": 0},
        )
        when = _as_utc(c.closed_at).date()
        g["all_time"] += c.realized_pnl
        g["trade_count"] += 1
        if c.won:
            g["wins"] += 1
        else:
            g["losses"] += 1
        if when == today:
            g["today"] += c.realized_pnl
        if when >= week_start:
            g["week"] += c.realized_pnl

    rows = []
    for g in groups.values():
        total = g["wins"] + g["losses"]
        rows.append(
            {
                "account_id": g["account_id"],
                "today": round(g["today"], 2),
                "week": round(g["week"], 2),
                "all_time": round(g["all_time"], 2),
                "wins": g["wins"],
                "losses": g["losses"],
                "trade_count": g["trade_count"],
                "win_rate": round(g["wins"] / total, 4) if total else None,
            }
        )
    rows.sort(key=lambda r: r["all_time"], reverse=True)
    return rows


def winrate_by(closes: Iterable[TradeClose], key: str = "indicator") -> list[dict]:
    """Win rate + P&L grouped by 'indicator' or 'symbol', sorted by trade count."""

    groups: dict[str, dict] = {}
    for c in closes:
        name = c.indicator if key == "indicator" else c.symbol
        g = groups.setdefault(name, {"name": name, "wins": 0, "losses": 0, "pnl": 0.0})
        g["pnl"] += c.realized_pnl
        if c.won:
            g["wins"] += 1
        else:
            g["losses"] += 1
    rows = []
    for g in groups.values():
        total = g["wins"] + g["losses"]
        rows.append(
            {
                "name": g["name"],
                "wins": g["wins"],
                "losses": g["losses"],
                "total": total,
                "win_rate": round(g["wins"] / total, 4) if total else None,
                "pnl": round(g["pnl"], 2),
            }
        )
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


@dataclass
class ServiceProbe:
    name: str
    up: bool
    detail: str = ""


@dataclass
class SystemHealth:
    token_status: str
    token_read_only: bool
    services: list[ServiceProbe] = field(default_factory=list)
    quote_freshness_seconds: Optional[float] = None
    stale_quote_count: int = 0
    total_quote_count: int = 0

    def as_dict(self) -> dict:
        return {
            "token_status": self.token_status,
            "token_read_only": self.token_read_only,
            "services": [{"name": s.name, "up": s.up, "detail": s.detail} for s in self.services],
            "quote_freshness_seconds": self.quote_freshness_seconds,
            "stale_quotes": f"{self.stale_quote_count} of {self.total_quote_count}",
            "all_up": all(s.up for s in self.services) if self.services else False,
        }
