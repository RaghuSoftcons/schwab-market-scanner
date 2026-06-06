"""Local fixture option-chain provider for dashboard proposal testing."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone

from nt_schwab_bridge.config import OptionPlannerConfig
from nt_schwab_bridge.models import OptionContractSnapshot, OptionRight, SignalRecord


class DemoOptionChainProvider:
    """Generate deterministic, in-memory option chains for local UI testing."""

    provider_kind = "demo"
    provider_name = "Demo Chain"
    provider_notes = ["In-memory fixture chain; no Schwab market-data call."]

    def __init__(self, config: OptionPlannerConfig) -> None:
        self.config = config
        self.last_underlying_price: float | None = None

    def __call__(self, record: SignalRecord) -> Sequence[OptionContractSnapshot]:
        source_symbol = record.payload.symbol.upper()
        symbol = self.config.option_symbol_for(source_symbol)
        self.last_underlying_price = None
        if symbol not in self.config.allowed_symbols:
            return []
        rights = self.config.proposal_rights_by_symbol.get(symbol) or [
            "CALL" if record.payload.direction == "long" else "PUT"
        ]
        now = datetime.now(timezone.utc)
        anchor_source = record.payload.underlying_price if source_symbol == symbol else None
        anchor = _round_to_increment(anchor_source or 620.0, self.config.spread_width_points)
        self.last_underlying_price = anchor
        contracts: list[OptionContractSnapshot] = []
        for label in self.config.expiries:
            expiry = _resolve_expiry_label(label, now.date())
            if expiry is None:
                continue
            for right in rights:
                long_strike = anchor
                short_strike = (
                    anchor + self.config.spread_width_points
                    if right == "CALL"
                    else anchor - self.config.spread_width_points
                )
                contracts.append(
                    _contract(
                        symbol=symbol,
                        expiry=expiry,
                        strike=long_strike,
                        right=right,
                        bid=2.8,
                        ask=2.9,
                        mark=2.85,
                        delta=0.52 if right == "CALL" else -0.52,
                        open_interest=800,
                        volume=240,
                        timestamp=now,
                    )
                )
                contracts.append(
                    _contract(
                        symbol=symbol,
                        expiry=expiry,
                        strike=short_strike,
                        right=right,
                        bid=1.0,
                        ask=1.15,
                        mark=1.08,
                        delta=0.25 if right == "CALL" else -0.25,
                        open_interest=700,
                        volume=180,
                        timestamp=now,
                    )
                )
        return contracts


def _contract(
    *,
    symbol: str,
    expiry: date,
    strike: float,
    right: OptionRight,
    bid: float,
    ask: float,
    mark: float,
    delta: float,
    open_interest: int,
    volume: int,
    timestamp: datetime,
) -> OptionContractSnapshot:
    return OptionContractSnapshot(
        symbol=symbol,
        broker_symbol=_broker_option_symbol(symbol, expiry, strike, right),
        expiry=expiry,
        strike=strike,
        right=right,
        bid=bid,
        ask=ask,
        last=mark,
        mark=mark,
        implied_volatility=0.22,
        delta=delta,
        theta=-0.12,
        open_interest=open_interest,
        volume=volume,
        timestamp=timestamp,
    )


def _resolve_expiry_label(label: str, as_of_date: date) -> date | None:
    normalized = label.upper().strip()
    if normalized.endswith("DTE") and normalized[:-3].isdigit():
        return _add_business_days(as_of_date, int(normalized[:-3]))
    if normalized in {"THIS_FRIDAY", "THIS FRIDAY"}:
        return _friday_for_week(as_of_date)
    if normalized in {"NEXT_WEEK_FRIDAY", "NEXT WEEK FRIDAY", "NEXT_FRIDAY"}:
        return _friday_for_week(as_of_date) + timedelta(days=7)
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _friday_for_week(as_of_date: date) -> date:
    days_until_friday = (4 - as_of_date.weekday()) % 7
    return as_of_date + timedelta(days=days_until_friday)


def _add_business_days(as_of_date: date, days: int) -> date:
    if days <= 0:
        return as_of_date
    current = as_of_date
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _round_to_increment(value: float, increment: float) -> float:
    if increment <= 0:
        return round(value, 2)
    return round(round(value / increment) * increment, 2)


def _broker_option_symbol(symbol: str, expiry: date, strike: float, right: OptionRight) -> str:
    compact_strike = f"{int(round(strike * 1000)):08d}"
    return f"{symbol.upper():<6}{expiry:%y%m%d}{right[0]}{compact_strike}"
