from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from nt_schwab_bridge.config import SchwabConfig
from nt_schwab_bridge.schwab_adapter import SchwabApiError, SchwabMarketDataClient

from market_scanner.models import Candle, EquityQuote


class SchwabEquityDataClient:
    """Small equity-data wrapper using the same Schwab OAuth client as the NT bridge."""

    def __init__(self, config: SchwabConfig):
        self._client = SchwabMarketDataClient(config)

    @property
    def raw_client(self) -> SchwabMarketDataClient:
        return self._client

    def get_quotes(self, symbols: Iterable[str]) -> dict[str, EquityQuote]:
        clean_symbols = [symbol.upper().replace("$", "").strip() for symbol in symbols if symbol.strip()]
        if not clean_symbols:
            return {}
        joined = ",".join(clean_symbols)
        payload, status, text = self._client._get_json_with_status(
            "/marketdata/v1/quotes",
            params={"symbols": joined, "fields": "quote,regular,extended,reference"},
        )
        if status >= 400:
            quotes: dict[str, EquityQuote] = {}
            for symbol in clean_symbols:
                quotes[symbol] = self.get_quote(symbol)
            return quotes
        return {symbol: _parse_quote(symbol, payload.get(symbol) or payload.get(symbol.upper()) or {}) for symbol in clean_symbols}

    def get_quote(self, symbol: str) -> EquityQuote:
        normalized = symbol.upper().replace("$", "").strip()
        attempts = [
            ("/marketdata/v1/quotes", {"symbols": normalized, "fields": "quote,regular,extended,reference"}),
            (f"/marketdata/v1/{normalized}/quotes", None),
        ]
        last_error = ""
        for path, params in attempts:
            payload, status, text = self._client._get_json_with_status(path, params=params)
            if status >= 400:
                last_error = text[:200]
                continue
            node = payload.get(normalized) if isinstance(payload, dict) else {}
            return _parse_quote(normalized, node or payload)
        raise SchwabApiError(f"Schwab quote request failed for {normalized}: {last_error}")

    def get_intraday_candles(self, symbol: str) -> list[Candle]:
        return self._price_history(
            symbol,
            {
                "periodType": "day",
                "period": "10",
                "frequencyType": "minute",
                "frequency": "1",
                "needExtendedHoursData": "true",
                "needPreviousClose": "true",
            },
        )

    def get_daily_candles(self, symbol: str) -> list[Candle]:
        return self._price_history(
            symbol,
            {
                "periodType": "year",
                "period": "1",
                "frequencyType": "daily",
                "frequency": "1",
                "needExtendedHoursData": "false",
                "needPreviousClose": "true",
            },
        )

    def _price_history(self, symbol: str, params: dict[str, str]) -> list[Candle]:
        normalized = symbol.upper().replace("$", "").strip()
        payload, status, text = self._client._get_json_with_status(
            "/marketdata/v1/pricehistory",
            params={"symbol": normalized, **params},
        )
        if status >= 400:
            raise SchwabApiError(f"Schwab pricehistory request failed for {normalized}: {status} {text[:200]}")
        candles = payload.get("candles", []) if isinstance(payload, dict) else []
        if not isinstance(candles, list):
            return []
        return [_parse_candle(item) for item in candles if isinstance(item, dict)]


def _parse_quote(symbol: str, payload: dict[str, Any]) -> EquityQuote:
    quote = payload.get("quote") if isinstance(payload.get("quote"), dict) else payload
    regular = payload.get("regular") if isinstance(payload.get("regular"), dict) else {}
    extended = payload.get("extended") if isinstance(payload.get("extended"), dict) else {}
    values = [extended, quote, regular, payload]

    def first_float(keys: tuple[str, ...]) -> float | None:
        for node in values:
            for key in keys:
                parsed = _optional_float(node.get(key))
                if parsed is not None:
                    return parsed
        return None

    def first_int(keys: tuple[str, ...]) -> int | None:
        for node in values:
            for key in keys:
                parsed = _optional_int(node.get(key))
                if parsed is not None:
                    return parsed
        return None

    timestamp_raw = None
    for node in values:
        for key in (
            "quoteTimeInLong",
            "tradeTimeInLong",
            "regularMarketTradeTimeInLong",
            "quoteTime",
            "tradeTime",
            "regularMarketTradeTime",
            "lastPriceTime",
        ):
            if node.get(key):
                timestamp_raw = node.get(key)
                break
        if timestamp_raw:
            break

    bid = first_float(("bidPrice", "bid"))
    ask = first_float(("askPrice", "ask"))
    last = first_float(
        (
            "lastPrice",
            "last",
            "extendedMarketLastPrice",
            "regularMarketLastPrice",
            "mark",
            "markPrice",
        )
    )
    mark = first_float(("mark", "markPrice", "lastPrice", "last"))
    return EquityQuote(
        symbol=symbol.upper(),
        bid=bid,
        ask=ask,
        last=last,
        mark=mark,
        total_volume=first_int(("totalVolume", "regularMarketTotalVolume", "volume")),
        timestamp=_timestamp_from_epoch(timestamp_raw) if timestamp_raw else None,
        raw=payload,
    )


def _parse_candle(item: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=_timestamp_from_epoch(item.get("datetime")),
        open=float(item.get("open") or 0),
        high=float(item.get("high") or 0),
        low=float(item.get("low") or 0),
        close=float(item.get("close") or 0),
        volume=int(item.get("volume") or 0),
    )


def _timestamp_from_epoch(value: Any) -> datetime:
    try:
        epoch = float(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).replace(microsecond=0)
    if epoch > 10_000_000_000:
        epoch /= 1000
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(microsecond=0)


def _optional_float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        parsed = None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed is None or parsed >= 0 else None
