"""Pydantic models for NT8 signal intake."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


Direction = Literal["long", "short"]
EntryType = Literal["market", "limit", "stop", "stop_limit"]
SignalStatus = Literal["accepted", "duplicate"]
ReviewStatus = Literal["pending_phase_1", "blocked", "duplicate", "reviewed"]
DecisionStatus = Literal["review_required", "blocked", "ready"]
DecisionRoute = Literal["none", "dashboard_review", "schwab_preview", "schwab_order"]
OptionRight = Literal["CALL", "PUT"]
ProposalLegAction = Literal["BUY", "SELL"]
ProposalStructure = Literal["single", "debit_vertical"]
ProposalStatus = Literal["proposed", "blocked"]
ProposalProviderKind = Literal["none", "demo", "schwab", "injected", "unknown"]
QuoteFreshnessStatus = Literal["not_checked", "fresh", "mixed", "stale"]
SchwabAccountType = Literal["cash", "margin", "unknown"]
SchwabAccountSource = Literal["configured", "discovered"]
ProposalSendStatus = Literal["blocked", "dry_run", "submitted"]
ProposalOrderFillStatus = Literal["not_sent", "unknown", "open", "partial", "filled", "canceled", "rejected", "error"]
SchwabMarketDataStatus = Literal[
    "disabled",
    "not_configured",
    "auth_ready",
    "refresh_ready",
    "auth_required",
    "config_error",
]
SchwabOptionChainCheckStatus = Literal["disabled", "not_configured", "auth_required", "received", "error"]


class IndicatorSnapshot(BaseModel):
    """Indicator-specific context sent by an NT8 signal adapter."""

    name: str
    small_arrow_plot: str | None = None
    large_arrow_plot: str | None = None
    same_bar: bool = False
    lookback_bars: int = Field(default=0, ge=0, le=20)
    large_arrow_bars_ago: int | None = Field(default=None, ge=0, le=20)
    small_arrow_bars_ago: int | None = Field(default=None, ge=0, le=20)
    arrow_bars_apart: int | None = Field(default=None, ge=0, le=20)
    magenta_detected: bool = False
    raw_values: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class SignalPayload(BaseModel):
    """Normalized signal payload posted by NT8."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    signal_id: str | None = None
    strategy: str
    symbol: str
    direction: Direction = Field(validation_alias=AliasChoices("direction", "side"))
    qty: int = Field(default=1, ge=1)
    entry_type: EntryType = "market"
    entry_limit_price: float | None = Field(default=None, gt=0)
    underlying_price: float | None = Field(default=None, gt=0)
    stop_loss_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)
    profit_target_percentages: list[float] = Field(default_factory=list)
    profit_target_policy: str = ""
    timeframe: str = "5m"
    timestamp: datetime
    bar_time: datetime | None = None
    bar_index: int | None = Field(default=None, ge=0)
    signal_type: str = "generic"
    source_indicator: str | None = None
    indicator: IndicatorSnapshot | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        symbol = value.upper().replace("$", "").strip()
        if not symbol:
            raise ValueError("symbol is required")
        return symbol

    @field_validator("strategy", "timeframe", "signal_type")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip()

    @field_validator("timestamp", "bar_time")
    @classmethod
    def ensure_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        tags = [tag.strip() for tag in value if tag and tag.strip()]
        return list(dict.fromkeys(tags))

    @field_validator("profit_target_percentages")
    @classmethod
    def normalize_profit_target_percentages(cls, value: list[float]) -> list[float]:
        targets: list[float] = []
        for target in value:
            if target <= 0 or target > 1000:
                raise ValueError("profit target percentages must be positive")
            targets.append(round(float(target), 4))
        return targets

    @model_validator(mode="after")
    def validate_entry_price(self) -> SignalPayload:
        if self.entry_type == "limit" and self.entry_limit_price is None:
            raise ValueError("entry_limit_price is required for limit entries")
        return self

    def duplicate_fingerprint(self) -> str:
        event_time = self.bar_time or self.timestamp
        basis = [
            self.signal_id or "",
            self.strategy,
            self.symbol,
            self.direction,
            self.signal_type,
            self.timeframe,
            event_time.isoformat(),
            "" if self.bar_index is None else str(self.bar_index),
        ]
        return hashlib.sha256("|".join(basis).encode("utf-8")).hexdigest()


class SignalDecision(BaseModel):
    """Risk/route decision for a normalized signal."""

    status: DecisionStatus
    route: DecisionRoute
    reasons: list[str] = Field(default_factory=list)
    target_dollars: float | None = Field(default=None, ge=0)
    stop_loss_dollars: float | None = Field(default=None, ge=0)
    execution_mode: Literal["dry_run", "live"] = "dry_run"
    allow_live_orders: bool = False
    indicator_source: str | None = None
    notes: str = ""


class OptionContractSnapshot(BaseModel):
    """Normalized option-chain contract used by the dry-run planner."""

    symbol: str
    broker_symbol: str = ""
    expiry: date
    strike: float = Field(gt=0)
    right: OptionRight
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    last: float | None = Field(default=None, ge=0)
    mark: float | None = Field(default=None, ge=0)
    implied_volatility: float | None = Field(default=None, ge=0)
    delta: float | None = Field(default=None, ge=-1, le=1)
    gamma: float | None = None  # for GEX wall computation
    theta: float | None = None
    open_interest: int | None = Field(default=None, ge=0)
    volume: int | None = Field(default=None, ge=0)
    timestamp: datetime

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        symbol = value.upper().replace("$", "").strip()
        if not symbol:
            raise ValueError("symbol is required")
        return symbol

    @field_validator("timestamp")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class OptionProposalLeg(BaseModel):
    """A leg in a dry-run option proposal."""

    action: ProposalLegAction
    qty: int = Field(ge=1)
    symbol: str
    broker_symbol: str = ""
    expiry: date
    strike: float = Field(gt=0)
    right: OptionRight
    price: float = Field(ge=0)
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    mark: float | None = Field(default=None, ge=0)
    delta: float | None = Field(default=None, ge=-1, le=1)
    open_interest: int | None = Field(default=None, ge=0)
    volume: int | None = Field(default=None, ge=0)


class OptionProposalExitTarget(BaseModel):
    """Planned scale-out target for a proposal entry."""

    qty: int = Field(ge=1)
    target_percent: float = Field(gt=0)
    entry_limit_price: float = Field(ge=0)
    target_limit_price: float = Field(ge=0)
    estimated_profit: float = Field(ge=0)
    tos_exit_order_line: str = ""
    note: str = ""


class OptionProposal(BaseModel):
    """Ranked dry-run proposal generated from a signal and option-chain data."""

    id: str
    signal_id: str
    symbol: str
    direction: Direction
    structure: ProposalStructure
    status: ProposalStatus = "proposed"
    created_at: datetime
    expiry: date
    quantity: int = Field(ge=1)
    underlying_price: float | None = Field(default=None, gt=0)
    legs: list[OptionProposalLeg]
    debit: float = Field(ge=0)
    max_loss: float = Field(ge=0)
    natural_limit_price: float = Field(default=0, ge=0)
    natural_debit: float = Field(default=0, ge=0)
    send_limit_price: float | None = Field(default=None, ge=0)
    price_protection: str = ""
    width: float | None = Field(default=None, gt=0)
    net_delta: float | None = None
    score: float = 0
    score_breakdown: list[dict] = Field(default_factory=list)
    tos_order_line: str = ""
    exit_targets: list[OptionProposalExitTarget] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    dry_run: bool = True
    # GEX wall exits (Phase 5): when NT_GEX_WALL_EXITS is on and chain gamma is available,
    # the call wall feeds the target and the put wall feeds the stop. gex_stop_loss_dollars is
    # the capped stop loss -> never exceeds max_loss.
    gex_target_underlying: float | None = None
    gex_stop_underlying: float | None = None
    gex_stop_loss_dollars: float | None = None


class OptionProposalSource(BaseModel):
    """Safe metadata describing where proposal chain data came from."""

    kind: ProposalProviderKind = "none"
    name: str = "none"
    read_only: bool = True
    live_orders_enabled: bool = False
    notes: list[str] = Field(default_factory=list)


class OptionCandidateDiagnostic(BaseModel):
    """A non-actionable option candidate with planner rejection reasons."""

    expiry: date
    strike: float
    right: OptionRight
    bid: float | None = None
    ask: float | None = None
    mark: float | None = None
    delta: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    quote_time: datetime
    reasons: list[str] = Field(default_factory=list)


class OptionQuoteFreshness(BaseModel):
    """Summary of quote age for the chain inspected by the planner."""

    status: QuoteFreshnessStatus = "not_checked"
    checked_contract_count: int = 0
    stale_contract_count: int = 0
    stale_after_seconds: int = 0
    freshest_quote_time: datetime | None = None
    freshest_quote_age_seconds: float | None = Field(default=None, ge=0)


class OptionProposalResult(BaseModel):
    """Planner output for one originating signal."""

    signal_id: str
    generated_at: datetime
    source: OptionProposalSource = Field(default_factory=OptionProposalSource)
    underlying_price: float | None = Field(default=None, gt=0)
    proposals: list[OptionProposal] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    chain_contract_count: int = 0
    eligible_contract_count: int = 0
    candidate_diagnostics: list[OptionCandidateDiagnostic] = Field(default_factory=list)
    quote_freshness: OptionQuoteFreshness = Field(default_factory=OptionQuoteFreshness)


class SignalRecord(BaseModel):
    id: str
    payload: SignalPayload
    received_at: datetime
    status: SignalStatus = "accepted"
    review_status: ReviewStatus = "pending_phase_1"
    duplicate_of: str | None = None
    proposal_count: int = 0
    execution_mode: Literal["dry_run", "live"] = "dry_run"
    decision: SignalDecision | None = None


class SignalAcceptedResponse(BaseModel):
    id: str
    status: SignalStatus
    duplicate: bool
    duplicate_of: str | None = None
    received_at: datetime
    review_status: ReviewStatus
    decision: SignalDecision | None = None
    message: str


class SignalListResponse(BaseModel):
    count: int
    returned_count: int
    total_count: int
    limit: int
    signals: list[SignalRecord]


class SignalClearResponse(BaseModel):
    status: Literal["cleared"] = "cleared"
    cleared_count: int
    audit_log_cleared: bool


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "nt-schwab-bridge"
    execution_mode: str
    allow_live_orders: bool
    signal_count: int
    config: dict[str, Any]


class SchwabMarketDataStatusResponse(BaseModel):
    status: SchwabMarketDataStatus
    enabled: bool
    auto_refresh_enabled: bool = False
    provider_configured: bool
    read_only_ready: bool
    execution_ready: bool = False
    api_base_configured: bool
    token_store_configured: bool
    access_token_present: bool
    refresh_token_present: bool
    access_token_expires_at: datetime | None = None
    needs_refresh: bool
    client_id_configured: bool
    client_secret_configured: bool
    account_hash_configured: bool
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class SchwabOptionChainSample(BaseModel):
    expiry: date
    strike: float
    right: OptionRight
    bid: float | None = None
    ask: float | None = None
    delta: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    quote_time: datetime


class SchwabOptionChainCheckResponse(BaseModel):
    status: SchwabOptionChainCheckStatus
    symbol: str
    expiry: date | None = None
    contract_type: OptionRight | None = None
    read_only_ready: bool = False
    contract_count: int = 0
    underlying_price: float | None = None
    sample: list[SchwabOptionChainSample] = Field(default_factory=list)
    request_meta: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class SchwabAccountBalance(BaseModel):
    """Safe account balance summary for dashboard-only routing hints."""

    available_to_trade: float | None = None
    buying_power: float | None = None
    cash_balance: float | None = None
    source: str = ""
    updated_at: datetime | None = None
    error: str | None = None


class SchwabAccountRoute(BaseModel):
    """Safe account metadata for proposal routing in the dashboard."""

    id: str
    label: str
    account_number: str = ""
    source: SchwabAccountSource = "configured"
    account_type: SchwabAccountType = "unknown"
    supports_spreads: bool = False
    enabled: bool = True
    order_configured: bool = False
    balance: SchwabAccountBalance | None = None


class AccountSelectionResponse(BaseModel):
    accounts: list[SchwabAccountRoute] = Field(default_factory=list)
    selected_account_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AccountSelectionUpdateRequest(BaseModel):
    selected_account_ids: list[str] = Field(default_factory=list)

    @field_validator("selected_account_ids")
    @classmethod
    def normalize_selected_account_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))


class DashboardSettingsResponse(BaseModel):
    allow_itm: bool = False
    max_loss_dollars: int = Field(default=300, ge=0)
    max_loss_choices: list[int] = Field(default_factory=lambda: [200, 300, 400, 500])
    entry_offset_cents: int = Field(default=30, ge=0)
    entry_offset_choices: list[int] = Field(default_factory=lambda: [10, 20, 30, 40, 50])
    expiry_label: str = "1DTE"
    expiry_choices: list[str] = Field(
        default_factory=lambda: ["0DTE", "1DTE", "2DTE", "3DTE", "THIS_FRIDAY", "NEXT_WEEK_FRIDAY"]
    )
    target_percentages: list[float] = Field(default_factory=lambda: [20.0, 40.0, 50.0])


class DashboardSettingsUpdateRequest(BaseModel):
    allow_itm: bool | None = None
    max_loss_dollars: int | None = Field(default=None, ge=0)
    entry_offset_cents: int | None = Field(default=None, ge=0)
    expiry_label: str | None = None
    target_percentages: list[float] | None = Field(default=None, min_length=1, max_length=3)


class ProposalSendRequest(BaseModel):
    selected_account_ids: list[str] = Field(default_factory=list)
    confirm_live_order: bool = False
    quantity: int | None = Field(default=None, ge=1, le=10)
    limit_price: float | None = Field(default=None, gt=0)
    order_note: str = Field(default="", max_length=500)

    @field_validator("selected_account_ids")
    @classmethod
    def normalize_selected_account_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))

    @field_validator("order_note")
    @classmethod
    def normalize_order_note(cls, value: str) -> str:
        return value.strip()


class ProposalAccountSendResult(BaseModel):
    account_id: str
    account_label: str
    status: ProposalSendStatus
    reasons: list[str] = Field(default_factory=list)
    broker_order_id: str | None = None
    order_payload: dict[str, Any] | None = None
    order_note: str = ""


class ProposalSendResponse(BaseModel):
    status: ProposalSendStatus
    signal_id: str
    proposal_id: str
    selected_account_ids: list[str] = Field(default_factory=list)
    account_results: list[ProposalAccountSendResult] = Field(default_factory=list)
    order_note: str = ""
    notes: list[str] = Field(default_factory=list)


class ProposalExitTargetPreview(BaseModel):
    target_index: int = Field(ge=0)
    qty: int = Field(ge=1)
    target_percent: float = Field(gt=0)
    entry_fill_price: float = Field(gt=0)
    target_limit_price: float = Field(gt=0)
    estimated_profit: float = Field(ge=0)
    tos_exit_order_line: str = ""


class ProposalOrderFillAccountStatus(BaseModel):
    account_id: str
    account_label: str
    broker_order_id: str | None = None
    status: ProposalOrderFillStatus = "unknown"
    schwab_status: str = ""
    filled_quantity: float = Field(default=0, ge=0)
    remaining_quantity: float | None = Field(default=None, ge=0)
    average_fill_price: float | None = Field(default=None, gt=0)
    order_payload: dict[str, Any] | None = None
    exit_targets: list[ProposalExitTargetPreview] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProposalOrderStatusResponse(BaseModel):
    signal_id: str
    proposal_id: str
    generated_at: datetime
    account_statuses: list[ProposalOrderFillAccountStatus] = Field(default_factory=list)
    has_filled_accounts: bool = False
    notes: list[str] = Field(default_factory=list)


class ProposalExitSendRequest(BaseModel):
    selected_account_ids: list[str] = Field(default_factory=list)
    confirm_live_order: bool = False
    order_note: str = Field(default="", max_length=500)

    @field_validator("selected_account_ids")
    @classmethod
    def normalize_selected_account_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))

    @field_validator("order_note")
    @classmethod
    def normalize_order_note(cls, value: str) -> str:
        return value.strip()


class DashboardSummaryResponse(BaseModel):
    signal_count: int
    recent_count: int
    duplicate_count: int
    decision_counts: dict[str, int]
    review_status_counts: dict[str, int] = Field(default_factory=dict)
    latest_signal: SignalRecord | None = None
    config: dict[str, Any]
