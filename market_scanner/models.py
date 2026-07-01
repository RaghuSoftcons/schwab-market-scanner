from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from nt_schwab_bridge.models import OptionProposal


Bias = Literal["bullish", "bearish", "mixed", "unknown"]
CandidateAction = Literal["CALL_BIAS", "PUT_BIAS", "WATCH", "AVOID"]
ScanSession = Literal["overnight", "premarket", "regular", "after_hours", "closed"]


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class EquityQuote(BaseModel):
    symbol: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    mark: float | None = None
    total_volume: int | None = None
    timestamp: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class TickerMetrics(BaseModel):
    symbol: str
    target_date: date | None = None
    current_price: float | None = None
    previous_close: float | None = None
    previous_high: float | None = None
    previous_low: float | None = None
    sma200: float | None = None
    gap_pct: float | None = None
    premarket_high: float | None = None
    premarket_low: float | None = None
    premarket_volume: int = 0
    today_high: float | None = None
    today_low: float | None = None
    vwap: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread_pct: float | None = None
    latest_bar_time: datetime | None = None
    data_notes: list[str] = Field(default_factory=list)


class RegimeSymbolState(BaseModel):
    symbol: str
    bias: Bias
    score: float = 0
    metrics: TickerMetrics
    reasons: list[str] = Field(default_factory=list)


class MarketRegime(BaseModel):
    bias: Bias
    score: float
    symbols: list[RegimeSymbolState]
    reasons: list[str] = Field(default_factory=list)


class ScannerCandidate(BaseModel):
    rank: int
    symbol: str
    action: CandidateAction
    direction: Literal["long", "short", "none"]
    score: float
    metrics: TickerMetrics
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    proposals: list[OptionProposal] = Field(default_factory=list)
    proposal_blocked_reasons: list[str] = Field(default_factory=list)


class ScanResult(BaseModel):
    scan_id: str
    scanned_at: datetime
    session: ScanSession
    universe: list[str]
    regime: MarketRegime
    candidates: list[ScannerCandidate]
    top_candidates: list[ScannerCandidate]
    notes: list[str] = Field(default_factory=list)


class SendProposalRequest(BaseModel):
    selected_account_ids: list[str] = Field(default_factory=list)
    confirm_live_order: bool = False
    quantity: int | None = Field(default=None, ge=1, le=10)
    limit_price: float | None = Field(default=None, gt=0)
    order_note: str = Field(default="", max_length=500)
    # OTOCO ("1st Triggers OCO"): when true, single-leg entries are placed as N bracketed slices
    # (one TRIGGER entry per target slice, each triggering an OCO of [target LIMIT, stop STOP]),
    # so exits are attached at the broker on fill. Ignored for verticals. Default off.
    otoco: bool = False


class SendExitTargetRequest(BaseModel):
    selected_account_ids: list[str] = Field(default_factory=list)
    confirm_live_order: bool = False
    order_note: str = Field(default="", max_length=500)


class ClosePositionRequest(BaseModel):
    selected_account_ids: list[str] = Field(default_factory=list)
    confirm_live_order: bool = False


class CloseContractRequest(BaseModel):
    # Close a single option contract in one account via a MARKET order (used by both
    # the tracked and the full-Schwab Open Positions views).
    account_id: str
    broker_symbol: str
    qty: int = Field(ge=1)
    is_long: bool = True
    confirm_live_order: bool = False


class PositionRow(BaseModel):
    # Unified row for the Open Positions table (Unified-Platform style). Used by both modes:
    #   tracked -> positions THIS dashboard sent this session; all -> every Schwab option position.
    account_id: str = ""        # raw id (for the close request)
    account_label: str = ""     # alias for display
    symbol: str = ""            # broker option symbol, e.g. "BRKB  260918C00490000"
    underlying: str = ""
    qty: float = 0.0            # signed net quantity (+long / -short)
    avg: float | None = None    # average open price
    mark: float | None = None   # current mark price
    unrealized_pnl: float | None = None
    direction: str = ""
    closeable: bool = False     # single-leg -> Close button; spread -> view-only
    is_spread: bool = False
    source: str = "schwab"      # tracked | schwab
    sent_at: str = ""
    target_price: float | None = None   # resting closing-LIMIT price (the profit target), if any
    stop_price: float | None = None      # resting closing-STOP trigger (the protective stop), if any
    stop_trailing: bool = False          # True once an armed native TRAILING_STOP is resting
    stop_trail_offset: float | None = None  # the trail distance ($) when stop_trailing (for the ⤴ display)
    spread_id: str | None = None        # shared id for the two legs of one vertical (combine in UI)
    is_spread_leg: bool = False         # one leg of a vertical -> Close blocked (naked-option guard)
    spread_aggregated: bool = False     # Schwab blended this strike across spreads (can't split)
    spread_kind: str = ""               # vertical | calendar | butterfly | broken_wing | condor | iron_condor | iron_fly
    tracked: bool = False               # symbol was sent by this dashboard this session


class PositionsResponse(BaseModel):
    generated_at: str
    mode: str = "tracked"       # tracked | all
    positions: list[PositionRow] = Field(default_factory=list)
    note: str = ""
    errors: list[str] = Field(default_factory=list)


class ClosePositionResult(BaseModel):
    account_id: str
    account_label: str
    status: Literal["blocked", "dry_run", "submitted"]
    reasons: list[str] = Field(default_factory=list)
    broker_order_id: str | None = None
    canceled_order_ids: list[str] = Field(default_factory=list)
    order_payload: dict[str, Any] | None = None


class ClosePositionResponse(BaseModel):
    status: Literal["blocked", "dry_run", "submitted"]
    symbol: str
    account_results: list[ClosePositionResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AccountSendResult(BaseModel):
    account_id: str
    account_label: str
    status: Literal["blocked", "dry_run", "submitted"]
    reasons: list[str] = Field(default_factory=list)
    broker_order_id: str | None = None
    order_payload: dict[str, Any] | None = None


class SendProposalResponse(BaseModel):
    status: Literal["blocked", "dry_run", "submitted"]
    proposal_id: str
    selected_account_ids: list[str]
    account_results: list[AccountSendResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


ProposalOrderFillStatus = Literal["not_sent", "unknown", "open", "partial", "filled", "canceled", "rejected", "error"]


class ProposalExitTargetPreview(BaseModel):
    target_index: int = Field(ge=0)
    qty: int = Field(ge=1)
    target_percent: float = Field(gt=0)
    entry_fill_price: float = Field(gt=0)
    target_limit_price: float = Field(gt=0)
    stop_loss_percent: float = Field(default=50.0, ge=0)
    stop_trigger_price: float = Field(default=0, ge=0)
    estimated_profit: float = Field(ge=0)
    tos_exit_order_line: str = ""
    tos_stop_order_line: str = ""


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
    proposal_id: str
    generated_at: datetime
    account_statuses: list[ProposalOrderFillAccountStatus] = Field(default_factory=list)
    has_filled_accounts: bool = False
    notes: list[str] = Field(default_factory=list)
