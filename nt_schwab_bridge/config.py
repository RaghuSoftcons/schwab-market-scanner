"""Configuration loading for the local bridge."""

from __future__ import annotations

import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


ExecutionMode = Literal["dry_run", "live"]
OptionRightConfig = Literal["CALL", "PUT"]
SchwabAccountType = Literal["cash", "margin", "unknown"]
SchwabAccountSource = Literal["configured", "discovered"]


class ServiceConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=5001, ge=1, le=65535)
    execution_mode: ExecutionMode = "dry_run"
    allow_live_orders: bool = False


class SignalConfig(BaseModel):
    max_recent: int = Field(default=500, ge=1, le=10000)
    duplicate_window_seconds: int = Field(default=30, ge=0, le=3600)
    default_timeframe: str = "5m"
    allowed_symbols: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "DIA", "SPX", "ES", "MES", "NQ", "MNQ", "NDX", "YM", "MYM"]
    )

    @field_validator("allowed_symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        symbols = [symbol.upper().strip() for symbol in value if symbol and symbol.strip()]
        return sorted(set(symbols))


class IndicatorSourceConfig(BaseModel):
    name: str
    enabled: bool = True
    signal_types: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("name")
    @classmethod
    def require_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("indicator source name cannot be blank")
        return name

    @field_validator("signal_types")
    @classmethod
    def normalize_signal_types(cls, value: list[str]) -> list[str]:
        signal_types = [signal_type.strip() for signal_type in value if signal_type and signal_type.strip()]
        return sorted(set(signal_types))


class IndicatorConfig(BaseModel):
    require_configured_source: bool = False
    sources: list[IndicatorSourceConfig] = Field(
        default_factory=lambda: [
            IndicatorSourceConfig(name="Ultimate AI Pro", enabled=True, signal_types=["double_arrow"]),
        ]
    )


class RiskConfig(BaseModel):
    enabled: bool = True
    trading_enabled: bool = False
    require_manual_review: bool = True
    max_quantity: int = Field(default=1, ge=1, le=100)
    allowed_directions: list[Literal["long", "short"]] = Field(default_factory=lambda: ["long", "short"])
    require_underlying_price: bool = True
    default_target_dollars: float = Field(default=275, ge=0)
    default_stop_loss_dollars: float = Field(default=175, ge=0)

    @field_validator("allowed_directions", mode="before")
    @classmethod
    def normalize_directions(cls, value: list[str] | str) -> list[str]:
        if isinstance(value, str):
            value = [value]
        directions = [direction.lower().strip() for direction in value if direction and direction.strip()]
        return sorted(set(directions))


class DashboardConfig(BaseModel):
    alerts_enabled: bool = True
    sound_enabled: bool = True


class OptionPlannerConfig(BaseModel):
    enabled: bool = True
    demo_chain_enabled: bool = False
    require_regular_options_session: bool = True
    regular_options_session_timezone: str = "America/New_York"
    regular_options_session_start: str = "09:30"
    regular_options_session_end: str = "16:15"
    allowed_symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "DIA"])
    symbol_map: dict[str, str] = Field(
        default_factory=lambda: {
            "ES": "SPY",
            "MES": "SPY",
            "SPX": "SPY",
            "NQ": "QQQ",
            "MNQ": "QQQ",
            "NDX": "QQQ",
            "YM": "DIA",
            "MYM": "DIA",
        }
    )
    expiries: list[str] = Field(default_factory=lambda: ["0DTE", "1DTE", "2DTE"])
    max_contracts: int = Field(default=5, ge=1, le=10)
    min_debit_per_trade: float = Field(default=300, ge=0)
    max_debit_per_trade: float = Field(default=500, ge=0)
    max_proposals_total: int = Field(default=4, ge=1, le=20)
    max_single_proposals_total: int = Field(default=2, ge=0, le=10)
    max_spread_proposals_total: int = Field(default=2, ge=0, le=10)
    proposal_rights_by_symbol: dict[str, list[OptionRightConfig]] = Field(
        default_factory=dict
    )
    target_delta_long: dict[str, list[float]] = Field(
        default_factory=lambda: {
            "0DTE": [0.30, 0.60],
            "1DTE": [0.30, 0.60],
            "2DTE": [0.30, 0.60],
            "3DTE": [0.30, 0.60],
            "THIS_FRIDAY": [0.30, 0.60],
            "NEXT_WEEK_FRIDAY": [0.30, 0.60],
        }
    )
    spread_width_points: float = Field(default=5, gt=0)
    max_proposals_per_expiry: int = Field(default=3, ge=1, le=20)
    max_bid_ask_spread_percent: float = Field(default=20, gt=0)
    min_open_interest: int = Field(default=100, ge=0)
    quote_stale_after_seconds: int = Field(default=300, ge=0)
    marketable_limit_symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "DIA"])
    marketable_limit_offset: float = Field(default=0.30, ge=0)
    exit_target_percentages: list[float] = Field(default_factory=list)
    allow_in_the_money_primary: bool = False

    @field_validator("allowed_symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        symbols = [symbol.upper().replace("$", "").strip() for symbol in value if symbol and symbol.strip()]
        return sorted(set(symbols))

    @field_validator("regular_options_session_timezone")
    @classmethod
    def validate_regular_options_session_timezone(cls, value: str) -> str:
        timezone_name = value.strip()
        if not timezone_name:
            raise ValueError("regular options session timezone cannot be blank")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown regular options session timezone: {timezone_name}") from exc
        return timezone_name

    @field_validator("regular_options_session_start", "regular_options_session_end")
    @classmethod
    def validate_regular_options_session_time(cls, value: str) -> str:
        return _parse_session_time(value).strftime("%H:%M")

    @field_validator("marketable_limit_symbols")
    @classmethod
    def normalize_marketable_limit_symbols(cls, value: list[str]) -> list[str]:
        symbols = [symbol.upper().replace("$", "").strip() for symbol in value if symbol and symbol.strip()]
        return sorted(set(symbols))

    @field_validator("symbol_map")
    @classmethod
    def normalize_symbol_map(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for source, target in value.items():
            source_symbol = _normalize_symbol(source)
            target_symbol = _normalize_symbol(target)
            if source_symbol and target_symbol:
                normalized[source_symbol] = target_symbol
        return normalized

    @field_validator("expiries")
    @classmethod
    def normalize_expiries(cls, value: list[str]) -> list[str]:
        expiries = [expiry.upper().strip() for expiry in value if expiry and expiry.strip()]
        return list(dict.fromkeys(expiries))

    @field_validator("exit_target_percentages")
    @classmethod
    def normalize_exit_target_percentages(cls, value: list[float]) -> list[float]:
        targets: list[float] = []
        for target in value:
            percent = round(float(target), 4)
            if percent <= 0 or percent > 1000:
                raise ValueError("exit target percentages must be between 0 and 1000")
            targets.append(percent)
        return targets[:3]

    @field_validator("target_delta_long")
    @classmethod
    def validate_delta_bands(cls, value: dict[str, list[float]]) -> dict[str, list[float]]:
        normalized: dict[str, list[float]] = {}
        for key, band in value.items():
            if len(band) != 2:
                raise ValueError(f"target delta band must have two values: {key}")
            low, high = sorted(float(item) for item in band)
            if low < 0 or high > 1:
                raise ValueError(f"target delta band must be between 0 and 1: {key}")
            normalized[key.upper().strip()] = [low, high]
        return normalized

    @field_validator("proposal_rights_by_symbol")
    @classmethod
    def normalize_proposal_rights(
        cls,
        value: dict[str, list[OptionRightConfig]],
    ) -> dict[str, list[OptionRightConfig]]:
        normalized: dict[str, list[OptionRightConfig]] = {}
        for symbol, rights in value.items():
            normalized_symbol = _normalize_symbol(symbol)
            normalized_rights = []
            for right in rights:
                normalized_right = right.upper().strip()
                if normalized_right not in {"CALL", "PUT"}:
                    raise ValueError(f"unsupported proposal right for {normalized_symbol}: {right}")
                normalized_rights.append(normalized_right)  # type: ignore[arg-type]
            normalized[normalized_symbol] = list(dict.fromkeys(normalized_rights))
        return normalized

    @model_validator(mode="after")
    def validate_debit_range(self) -> OptionPlannerConfig:
        if self.max_debit_per_trade < self.min_debit_per_trade:
            raise ValueError("max_debit_per_trade must be greater than or equal to min_debit_per_trade")
        return self

    def option_symbol_for(self, symbol: str) -> str:
        normalized = _normalize_symbol(symbol)
        return self.symbol_map.get(normalized, normalized)

    def regular_options_session_label(self) -> str:
        return (
            f"{self.regular_options_session_timezone}:"
            f"{self.regular_options_session_start}-{self.regular_options_session_end}"
        )

    def regular_options_session_block_reason(self, as_of: datetime | None = None) -> str | None:
        if not self.require_regular_options_session:
            return None
        local_now = _localized_session_time(as_of or datetime.now(timezone.utc), self.regular_options_session_timezone)
        start = _parse_session_time(self.regular_options_session_start)
        end = _parse_session_time(self.regular_options_session_end)
        local_clock = local_now.time().replace(tzinfo=None)
        if local_now.weekday() < 5 and _time_in_window(local_clock, start, end):
            return None
        return f"regular_options_session_closed:{self.regular_options_session_label()}"


class StorageConfig(BaseModel):
    persist_signals: bool = True
    signal_audit_path: str = ".local_state/signals.jsonl"
    proposal_audit_path: str = ".local_state/proposals.jsonl"
    account_selection_path: str = ".local_state/account_selections.json"
    dashboard_settings_path: str = ".local_state/dashboard_settings.json"
    order_audit_path: str = ".local_state/order_audit.jsonl"


class SchwabAccountConfig(BaseModel):
    """Local account-routing metadata without exposing account hashes in dashboard payloads."""

    id: str
    label: str = ""
    account_number: str = ""
    account_hash: str = ""
    source: SchwabAccountSource = "configured"
    account_type: SchwabAccountType = "unknown"
    supports_spreads: bool = False
    enabled: bool = True
    default_selected: bool = False

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("account id cannot be blank")
        return normalized

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return value.strip()

    @field_validator("account_number")
    @classmethod
    def normalize_account_number(cls, value: str) -> str:
        return value.strip()


class SchwabConfig(BaseModel):
    market_data_enabled: bool = False
    account_discovery_enabled: bool = True
    account_discovery_ttl_seconds: int = Field(default=60, ge=5, le=3600)
    auto_refresh_enabled: bool = False
    token_store_path: str = ""
    token_authority_url: str = ""
    token_authority_api_key: str = ""
    token_authority_cache_seconds: int = Field(default=60, ge=0, le=600)
    account_hash: str = ""
    import_existing_client: bool = True
    api_base_url: str = "https://api.schwabapi.com"
    token_url: str = "https://api.schwabapi.com/v1/oauth/token"
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    access_token_expires_at: str = ""
    refresh_token: str = ""
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    token_refresh_skew_seconds: int = Field(default=300, ge=0, le=3600)
    accounts: list[SchwabAccountConfig] = Field(default_factory=list)


class BridgeConfig(BaseModel):
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    signals: SignalConfig = Field(default_factory=SignalConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    options: OptionPlannerConfig = Field(default_factory=OptionPlannerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    schwab: SchwabConfig = Field(default_factory=SchwabConfig)

    def public_status(self) -> dict[str, object]:
        return {
            "execution_mode": self.service.execution_mode,
            "allow_live_orders": self.service.allow_live_orders,
            "allowed_symbols": self.signals.allowed_symbols,
            "indicator_sources_configured": [source.name for source in self.indicators.sources],
            "require_configured_indicator_source": self.indicators.require_configured_source,
            "risk_gate_enabled": self.risk.enabled,
            "trading_enabled": self.risk.trading_enabled,
            "manual_review_required": self.risk.require_manual_review,
            "max_quantity": self.risk.max_quantity,
            "default_target_dollars": self.risk.default_target_dollars,
            "default_stop_loss_dollars": self.risk.default_stop_loss_dollars,
            "dashboard_alerts_enabled": self.dashboard.alerts_enabled,
            "dashboard_sound_enabled": self.dashboard.sound_enabled,
            "options_planner_enabled": self.options.enabled,
            "options_demo_chain_enabled": self.options.demo_chain_enabled,
            "options_regular_session_required": self.options.require_regular_options_session,
            "options_regular_session": self.options.regular_options_session_label(),
            "options_allowed_symbols": self.options.allowed_symbols,
            "options_symbol_map": self.options.symbol_map,
            "options_expiries": self.options.expiries,
            "options_max_contracts": self.options.max_contracts,
            "options_min_debit_per_trade": self.options.min_debit_per_trade,
            "options_max_debit_per_trade": self.options.max_debit_per_trade,
            "options_max_proposals_total": self.options.max_proposals_total,
            "options_proposal_rights_by_symbol": self.options.proposal_rights_by_symbol,
            "options_marketable_limit_symbols": self.options.marketable_limit_symbols,
            "options_marketable_limit_offset": self.options.marketable_limit_offset,
            "options_allow_in_the_money_primary": self.options.allow_in_the_money_primary,
            "signal_persistence_enabled": self.storage.persist_signals,
            "signal_audit_path": self.storage.signal_audit_path if self.storage.persist_signals else "",
            "proposal_audit_path": self.storage.proposal_audit_path if self.storage.persist_signals else "",
            "account_selection_path": self.storage.account_selection_path,
            "dashboard_settings_path": self.storage.dashboard_settings_path,
            "order_audit_path": self.storage.order_audit_path,
            "schwab_market_data_enabled": self.schwab.market_data_enabled,
            "schwab_account_discovery_enabled": self.schwab.account_discovery_enabled,
            "schwab_auto_refresh_enabled": self.schwab.auto_refresh_enabled,
            "schwab_account_count": len([account for account in self.schwab.accounts if account.enabled]),
            "schwab_api_base_configured": bool(self.schwab.api_base_url),
            "schwab_token_store_configured": bool(self.schwab.token_store_path),
            "schwab_account_hash_configured": bool(self.schwab.account_hash),
            "schwab_client_id_configured": bool(self.schwab.client_id),
            "schwab_client_secret_configured": bool(self.schwab.client_secret),
            "schwab_access_token_configured": bool(self.schwab.access_token),
            "schwab_refresh_token_configured": bool(self.schwab.refresh_token),
            "schwab_read_only_configured": self.schwab.market_data_enabled
            and bool(self.schwab.api_base_url)
            and bool(self.schwab.token_store_path or self.schwab.access_token or self.schwab.refresh_token),
        }


def load_config(path: str | Path | None = None) -> BridgeConfig:
    resolved_path = Path(path or os.getenv("NT_SCHWAB_CONFIG", "config.yaml"))
    if not resolved_path.exists():
        return _apply_environment_overrides(BridgeConfig())

    with resolved_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {resolved_path}")
    return _apply_environment_overrides(BridgeConfig.model_validate(payload))


def _apply_environment_overrides(config: BridgeConfig) -> BridgeConfig:
    schwab_updates: dict[str, object] = {}
    option_updates: dict[str, object] = {}
    env_string_fields = {
        "SCHWAB_TOKEN_STORE_PATH": "token_store_path",
        "SCHWAB_TOKEN_AUTHORITY_URL": "token_authority_url",
        "SCHWAB_TOKEN_AUTHORITY_API_KEY": "token_authority_api_key",
        "TOKEN_AUTHORITY_API_KEY": "token_authority_api_key",
        "SCHWAB_ACCOUNT_HASH": "account_hash",
        "SCHWAB_API_BASE_URL": "api_base_url",
        "SCHWAB_TOKEN_URL": "token_url",
        "SCHWAB_CLIENT_ID": "client_id",
        "SCHWAB_CLIENT_SECRET": "client_secret",
        "SCHWAB_ACCESS_TOKEN": "access_token",
        "SCHWAB_ACCESS_TOKEN_EXPIRES_AT": "access_token_expires_at",
        "SCHWAB_REFRESH_TOKEN": "refresh_token",
    }
    for env_name, field_name in env_string_fields.items():
        value = os.getenv(env_name)
        if value is not None:
            schwab_updates[field_name] = value

    enabled = _env_bool("SCHWAB_MARKET_DATA_ENABLED")
    if enabled is not None:
        schwab_updates["market_data_enabled"] = enabled

    account_discovery_enabled = _env_bool("SCHWAB_ACCOUNT_DISCOVERY_ENABLED")
    if account_discovery_enabled is not None:
        schwab_updates["account_discovery_enabled"] = account_discovery_enabled

    account_discovery_ttl = _env_int("SCHWAB_ACCOUNT_DISCOVERY_TTL_SECONDS")
    if account_discovery_ttl is not None:
        schwab_updates["account_discovery_ttl_seconds"] = account_discovery_ttl

    auto_refresh_enabled = _env_bool("SCHWAB_AUTO_REFRESH_ENABLED")
    if auto_refresh_enabled is not None:
        schwab_updates["auto_refresh_enabled"] = auto_refresh_enabled

    timeout = _env_float("SCHWAB_TIMEOUT_SECONDS")
    if timeout is not None:
        schwab_updates["timeout_seconds"] = timeout

    refresh_skew = _env_int("SCHWAB_TOKEN_REFRESH_SKEW_SECONDS")
    if refresh_skew is not None:
        schwab_updates["token_refresh_skew_seconds"] = refresh_skew

    authority_cache_seconds = _env_int("SCHWAB_TOKEN_AUTHORITY_CACHE_SECONDS")
    if authority_cache_seconds is not None:
        schwab_updates["token_authority_cache_seconds"] = authority_cache_seconds

    demo_chain_enabled = _env_bool("NT_OPTIONS_DEMO_CHAIN_ENABLED")
    if demo_chain_enabled is not None:
        option_updates["demo_chain_enabled"] = demo_chain_enabled

    if not schwab_updates and not option_updates:
        service_updates: dict[str, object] = {}
        risk_updates: dict[str, object] = {}
    else:
        service_updates = {}
        risk_updates = {}

    execution_mode = os.getenv("NT_EXECUTION_MODE")
    if execution_mode is not None:
        normalized_mode = execution_mode.strip().lower()
        if normalized_mode not in {"dry_run", "live"}:
            raise ValueError("Environment variable NT_EXECUTION_MODE must be dry_run or live.")
        service_updates["execution_mode"] = normalized_mode

    allow_live_orders = _env_bool("NT_ALLOW_LIVE_ORDERS")
    if allow_live_orders is not None:
        service_updates["allow_live_orders"] = allow_live_orders

    trading_enabled = _env_bool("NT_TRADING_ENABLED")
    if trading_enabled is not None:
        risk_updates["trading_enabled"] = trading_enabled

    if not schwab_updates and not option_updates and not service_updates and not risk_updates:
        return config
    payload = config.model_dump()
    if service_updates:
        service = ServiceConfig.model_validate({**config.service.model_dump(), **service_updates})
        payload["service"] = service.model_dump()
    if risk_updates:
        risk = RiskConfig.model_validate({**config.risk.model_dump(), **risk_updates})
        payload["risk"] = risk.model_dump()
    if schwab_updates:
        schwab = SchwabConfig.model_validate({**config.schwab.model_dump(), **schwab_updates})
        payload["schwab"] = schwab.model_dump()
    if option_updates:
        options = OptionPlannerConfig.model_validate({**config.options.model_dump(), **option_updates})
        payload["options"] = options.model_dump()
    return BridgeConfig.model_validate(payload)


def _normalize_symbol(value: str) -> str:
    return value.upper().replace("$", "").strip()


def _parse_session_time(value: str) -> time:
    text = value.strip()
    try:
        return time.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"session time must be HH:MM: {value}") from exc


def _localized_session_time(value: datetime, timezone_name: str) -> datetime:
    zone = ZoneInfo(timezone_name)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone)


def _time_in_window(value: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= value <= end
    return value >= start or value <= end


def _env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be a boolean value.")


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return float(raw)


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return int(raw)
