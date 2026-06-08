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
