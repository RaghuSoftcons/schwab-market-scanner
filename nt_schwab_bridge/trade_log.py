"""
================================================================================
File:          trade_log.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 16:40 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 16:40 EST

Purpose:
    Append-only store of CLOSED trades, used to power the dashboard P&L, win-rate,
    equity-curve, and trade-history panels (brief Step 7). A close is recorded
    with its realized P&L; the store reloads from JSONL on startup so history
    survives restarts. Realized P&L is computed from net entry/exit prices:

        realized = (exit_net - entry_net) * 100 * contracts

    Closes can be recorded explicitly (POST /trades/close) or by a future hook
    that detects an exit-order fill -- both land in the same store.

Change Log:
    2026-06-13 16:40 EST  v1.0.0  Initial implementation (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from nt_schwab_bridge.dashboard_stats import (
    TradeClose,
    compute_pnl,
    equity_curve,
    pnl_by_account,
    trade_history,
    winrate_by,
)

UTC = timezone.utc


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            dt = datetime.now(UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class TradeLogStore:
    """Thread-safe append-only closed-trade log with JSONL persistence."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._closes: list[TradeClose] = []
        self._recorded_keys: set[str] = set()
        self._lock = Lock()
        self._load()

    def was_recorded(self, dedup_key: str) -> bool:
        with self._lock:
            return dedup_key in self._recorded_keys

    def record_close(
        self,
        *,
        symbol: str,
        indicator: str,
        account_id: str,
        entry_price: float,
        exit_price: float,
        contracts: int,
        closed_at: datetime | None = None,
        realized_pnl: float | None = None,
        dedup_key: str | None = None,
    ) -> TradeClose | None:
        """Record a closed trade. If realized_pnl is not given, it is computed
        from net entry/exit prices and contract count. When dedup_key is given
        and already seen (e.g. an exit order id), the close is skipped (None)."""

        if realized_pnl is None:
            realized_pnl = round((float(exit_price) - float(entry_price)) * 100.0 * int(contracts), 2)
        close = TradeClose(
            closed_at=closed_at or datetime.now(UTC),
            symbol=str(symbol).upper(),
            indicator=str(indicator),
            account_id=str(account_id),
            realized_pnl=float(realized_pnl),
            won=realized_pnl > 0,
        )
        with self._lock:
            if dedup_key and dedup_key in self._recorded_keys:
                return None
            if dedup_key:
                self._recorded_keys.add(dedup_key)
            self._closes.append(close)
            self._append(close, entry_price, exit_price, contracts, dedup_key)
        return close

    def closes(self) -> list[TradeClose]:
        with self._lock:
            return list(self._closes)

    def summary(self, *, now: datetime | None = None, history_limit: int = 50) -> dict:
        closes = self.closes()
        pnl = compute_pnl(closes, now=now)
        return {
            "pnl": pnl.as_dict(),
            "pnl_by_account": pnl_by_account(closes, now=now),
            "winrate_by_indicator": winrate_by(closes, "indicator"),
            "winrate_by_symbol": winrate_by(closes, "symbol"),
            "equity_curve": equity_curve(closes),
            "history": trade_history(closes)[:history_limit],
        }

    # ---- persistence -------------------------------------------------------

    def _append(self, close: TradeClose, entry_price, exit_price, contracts, dedup_key=None) -> None:
        payload = {
            "closed_at": close.closed_at.isoformat(),
            "symbol": close.symbol,
            "indicator": close.indicator,
            "account_id": close.account_id,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "contracts": contracts,
            "realized_pnl": close.realized_pnl,
            "won": close.won,
            "exit_order_id": dedup_key,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                e = json.loads(line)
                self._closes.append(
                    TradeClose(
                        closed_at=_parse_dt(e.get("closed_at")),
                        symbol=str(e.get("symbol", "")).upper(),
                        indicator=str(e.get("indicator", "")),
                        account_id=str(e.get("account_id", "")),
                        realized_pnl=float(e.get("realized_pnl", 0.0)),
                        won=bool(e.get("won", float(e.get("realized_pnl", 0.0)) > 0)),
                    )
                )
                key = e.get("exit_order_id")
                if key:
                    self._recorded_keys.add(str(key))
        except (OSError, json.JSONDecodeError):
            pass
