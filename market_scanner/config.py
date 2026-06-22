from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from nt_schwab_bridge.config import OptionPlannerConfig, SchwabConfig


def _split_csv(value: str, fallback: list[str]) -> list[str]:
    if not value.strip():
        return fallback
    return [item.strip().upper().replace("$", "") for item in re.split(r"[\s,]+", value) if item.strip()]


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _default_token_store_path() -> str:
    env_value = os.getenv("SCHWAB_TOKEN_STORE_PATH", "").strip()
    if env_value:
        return env_value
    local_shared = Path(r"D:\data\schwab\schwab_tokens.json")
    if local_shared.exists():
        return str(local_shared)
    return "/data/schwab/schwab_tokens.json"


def _default_storage_path() -> str:
    env_value = os.getenv("SCANNER_STORAGE_PATH", os.getenv("STORAGE_PATH", "")).strip()
    if env_value:
        return env_value
    if os.name != "nt" and Path("/data").exists():
        return "/data/scanner"
    return ".local_state"


class ServiceSettings(BaseModel):
    execution_mode: str = "dry_run"
    allow_live_orders: bool = False
    trading_enabled: bool = False
    api_key: str = ""

    @field_validator("execution_mode")
    @classmethod
    def normalize_execution_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"dry_run", "live"}:
            raise ValueError("execution_mode must be dry_run or live")
        return normalized

    @property
    def live_gate_open(self) -> bool:
        return self.execution_mode == "live" and self.allow_live_orders and self.trading_enabled


class ScannerSettings(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["AAPL", "NVDA", "JPM"])
    regime_symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "DIA"])
    top_n: int = Field(default=10, ge=1, le=100)
    interval_minutes: int = Field(default=30, ge=1, le=240)
    min_price: float = Field(default=3.0, ge=0)
    min_abs_gap_pct: float = Field(default=0.5, ge=0)
    min_premarket_volume: int = Field(default=50_000, ge=0)
    timezone: str = "America/New_York"

    @field_validator("symbols", "regime_symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        symbols = [item.upper().replace("$", "").strip() for item in values if item and item.strip()]
        return list(dict.fromkeys(symbols))


class OptionSettings(BaseModel):
    # Default to Friday weeklies (the AUTO expansion). 1DTE only suits index ETFs (SPY/QQQ/IWM)
    # that list daily expiries; ordinary equities have no next-day chain, so 1DTE blocked every
    # non-index candidate with "no_contracts_for_expiry". THIS_FRIDAY/NEXT_WEEK_FRIDAY is robust.
    expiries: list[str] = Field(default_factory=lambda: ["THIS_FRIDAY", "NEXT_WEEK_FRIDAY"])
    max_contracts: int = Field(default=5, ge=1, le=10)
    min_debit_per_trade: float = Field(default=100.0, ge=0)
    max_debit_per_trade: float = Field(default=500.0, ge=0)
    marketable_limit_offset: float = Field(default=0.30, ge=0)
    max_bid_ask_spread_percent: float = Field(default=20.0, gt=0)
    min_open_interest: int = Field(default=100, ge=0)
    quote_stale_after_seconds: int = Field(default=300, ge=0)


class StorageSettings(BaseModel):
    path: Path = Path(".local_state")


class AppSettings(BaseModel):
    service: ServiceSettings = Field(default_factory=ServiceSettings)
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)
    options: OptionSettings = Field(default_factory=OptionSettings)
    schwab: SchwabConfig = Field(default_factory=SchwabConfig)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    def planner_config(self) -> OptionPlannerConfig:
        symbols = list(dict.fromkeys([*self.scanner.symbols, *self.scanner.regime_symbols]))
        return OptionPlannerConfig(
            enabled=True,
            require_regular_options_session=False,
            allowed_symbols=symbols,
            symbol_map={},
            expiries=self.options.expiries,
            max_contracts=self.options.max_contracts,
            min_debit_per_trade=self.options.min_debit_per_trade,
            max_debit_per_trade=self.options.max_debit_per_trade,
            max_proposals_total=4,
            max_single_proposals_total=2,
            max_spread_proposals_total=2,
            max_bid_ask_spread_percent=self.options.max_bid_ask_spread_percent,
            min_open_interest=self.options.min_open_interest,
            quote_stale_after_seconds=self.options.quote_stale_after_seconds,
            marketable_limit_symbols=symbols,
            marketable_limit_offset=self.options.marketable_limit_offset,
            target_delta_long={
                "0DTE": [0.30, 0.60],
                "1DTE": [0.30, 0.60],
                "2DTE": [0.30, 0.60],
                "3DTE": [0.30, 0.60],
                "THIS_FRIDAY": [0.30, 0.60],
                "NEXT_WEEK_FRIDAY": [0.30, 0.60],
            },
        )

    def public_status(self) -> dict[str, Any]:
        return {
            "execution_mode": self.service.execution_mode,
            "allow_live_orders": self.service.allow_live_orders,
            "trading_enabled": self.service.trading_enabled,
            "live_gate_open": self.service.live_gate_open,
            "symbols": self.scanner.symbols,
            "regime_symbols": self.scanner.regime_symbols,
            "top_n": self.scanner.top_n,
            "interval_minutes": self.scanner.interval_minutes,
            "storage_path": str(self.storage.path),
            "schwab_market_data_enabled": self.schwab.market_data_enabled,
            "schwab_auto_refresh_enabled": self.schwab.auto_refresh_enabled,
            "schwab_token_store_configured": bool(self.schwab.token_store_path),
        }


@dataclass(frozen=True)
class SettingsLoadResult:
    settings: AppSettings
    source: str


def load_settings() -> SettingsLoadResult:
    config_path = os.getenv("SCANNER_CONFIG", "config.yaml").strip()
    raw: dict[str, Any] = {}
    source = "environment"
    if config_path and Path(config_path).exists():
        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        source = config_path

    service_raw = dict(raw.get("service", {}) or {})
    scanner_raw = dict(raw.get("scanner", {}) or {})
    options_raw = dict(raw.get("options", {}) or {})
    schwab_raw = dict(raw.get("schwab", {}) or {})
    storage_raw = dict(raw.get("storage", {}) or {})

    service_raw.update(
        {
            "execution_mode": os.getenv("SCANNER_EXECUTION_MODE", os.getenv("EXECUTION_MODE", service_raw.get("execution_mode", "dry_run"))),
            "allow_live_orders": _env_bool("SCANNER_ALLOW_LIVE_ORDERS", _env_bool("ALLOW_LIVE_ORDERS", bool(service_raw.get("allow_live_orders", False)))),
            "trading_enabled": _env_bool("SCANNER_TRADING_ENABLED", _env_bool("TRADING_ENABLED", bool(service_raw.get("trading_enabled", False)))),
            "api_key": os.getenv("SCANNER_API_KEY", os.getenv("GPT_ACTION_API_KEY", service_raw.get("api_key", ""))),
        }
    )
    scanner_raw.update(
        {
            "symbols": _split_csv(os.getenv("SCANNER_SYMBOLS", ""), scanner_raw.get("symbols", ["AAPL", "NVDA", "JPM"])),
            "regime_symbols": _split_csv(
                os.getenv("SCANNER_REGIME_SYMBOLS", ""),
                scanner_raw.get("regime_symbols", ["SPY", "QQQ", "DIA"]),
            ),
            "top_n": _env_int("SCANNER_TOP_N", int(scanner_raw.get("top_n", 10))),
            "interval_minutes": _env_int("SCANNER_INTERVAL_MINUTES", int(scanner_raw.get("interval_minutes", 30))),
            "min_price": _env_float("SCANNER_MIN_PRICE", float(scanner_raw.get("min_price", 3))),
            "min_abs_gap_pct": _env_float("SCANNER_MIN_ABS_GAP_PCT", float(scanner_raw.get("min_abs_gap_pct", 0.5))),
            "min_premarket_volume": _env_int(
                "SCANNER_MIN_PREMARKET_VOLUME",
                int(scanner_raw.get("min_premarket_volume", 50_000)),
            ),
        }
    )
    options_raw.update(
        {
            "expiries": _split_csv(os.getenv("SCANNER_OPTION_EXPIRIES", ""), options_raw.get("expiries", ["THIS_FRIDAY", "NEXT_WEEK_FRIDAY"])),
            "max_contracts": _env_int("SCANNER_MAX_CONTRACTS", int(options_raw.get("max_contracts", 5))),
            "min_debit_per_trade": _env_float(
                "SCANNER_MIN_DEBIT_PER_TRADE",
                float(options_raw.get("min_debit_per_trade", 100)),
            ),
            "max_debit_per_trade": _env_float(
                "SCANNER_MAX_DEBIT_PER_TRADE",
                float(options_raw.get("max_debit_per_trade", 500)),
            ),
            "marketable_limit_offset": _env_float(
                "SCANNER_MARKETABLE_LIMIT_OFFSET",
                float(options_raw.get("marketable_limit_offset", 0.30)),
            ),
        }
    )
    storage_raw.update(
        {
            "path": os.getenv(
                "SCANNER_STORAGE_PATH",
                os.getenv("STORAGE_PATH", storage_raw.get("path", _default_storage_path())),
            )
        }
    )

    schwab_raw.update(
        {
            "market_data_enabled": _env_bool(
                "SCHWAB_MARKET_DATA_ENABLED",
                bool(schwab_raw.get("market_data_enabled", True)),
            ),
            # Default OFF: the scanner consumes tokens read-only from the shared store so it
            # never races the rotating refresh_token. A single owner (the platform / external
            # refresher) writes new tokens; the scanner only reads. Override per-deployment
            # with SCHWAB_AUTO_REFRESH_ENABLED=true ONLY if this scanner is the sole token owner.
            "auto_refresh_enabled": _env_bool(
                "SCHWAB_AUTO_REFRESH_ENABLED",
                bool(schwab_raw.get("auto_refresh_enabled", False)),
            ),
            "token_store_path": _default_token_store_path(),
            "client_id": os.getenv("SCHWAB_CLIENT_ID", schwab_raw.get("client_id", "")),
            "client_secret": os.getenv("SCHWAB_CLIENT_SECRET", schwab_raw.get("client_secret", "")),
            "access_token": os.getenv("SCHWAB_ACCESS_TOKEN", schwab_raw.get("access_token", "")),
            "refresh_token": os.getenv("SCHWAB_REFRESH_TOKEN", schwab_raw.get("refresh_token", "")),
            "access_token_expires_at": os.getenv(
                "SCHWAB_ACCESS_TOKEN_EXPIRES_AT",
                schwab_raw.get("access_token_expires_at", ""),
            ),
            "import_existing_client": _env_bool(
                "SCHWAB_IMPORT_EXISTING_CLIENT",
                bool(schwab_raw.get("import_existing_client", True)),
            ),
        }
    )

    return SettingsLoadResult(
        settings=AppSettings(
            service=ServiceSettings.model_validate(service_raw),
            scanner=ScannerSettings.model_validate(scanner_raw),
            options=OptionSettings.model_validate(options_raw),
            schwab=SchwabConfig.model_validate(schwab_raw),
            storage=StorageSettings.model_validate(storage_raw),
        ),
        source=source,
    )
