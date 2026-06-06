"""FastAPI app for Phase 1 signal intake."""

from __future__ import annotations

import logging
import math
import re
import struct
import subprocess
import sys
import threading
import time
import wave
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from nt_schwab_bridge.account_selection import AccountSelectionStore
from nt_schwab_bridge.config import BridgeConfig, load_config
from nt_schwab_bridge.dashboard import render_dashboard_html
from nt_schwab_bridge.dashboard_settings import DashboardSettingsStore
from nt_schwab_bridge.decision import SignalDecisionEngine
from nt_schwab_bridge.demo_provider import DemoOptionChainProvider
from nt_schwab_bridge.models import (
    AccountSelectionResponse,
    AccountSelectionUpdateRequest,
    DashboardSummaryResponse,
    DashboardSettingsResponse,
    DashboardSettingsUpdateRequest,
    HealthResponse,
    OptionContractSnapshot,
    OptionProposal,
    OptionProposalExitTarget,
    OptionProposalLeg,
    OptionProposalResult,
    OptionProposalSource,
    ProposalExitSendRequest,
    ProposalExitTargetPreview,
    ProposalAccountSendResult,
    ProposalOrderFillAccountStatus,
    ProposalOrderStatusResponse,
    ProposalSendRequest,
    ProposalSendResponse,
    SignalAcceptedResponse,
    SignalClearResponse,
    SignalDecision,
    SignalListResponse,
    SignalPayload,
    SignalRecord,
    SchwabAccountBalance,
    SchwabAccountRoute,
    SchwabMarketDataStatusResponse,
    SchwabOptionChainCheckResponse,
)
from nt_schwab_bridge.order_audit import OrderAuditStore
from nt_schwab_bridge.planner import OptionProposalPlanner
from nt_schwab_bridge.schwab_adapter import (
    SchwabApiError,
    SchwabMarketDataClient,
    SchwabOAuthError,
    build_schwab_option_chain_provider,
    discover_schwab_accounts,
    schwab_market_data_status,
    schwab_option_chain_check,
)
from nt_schwab_bridge.store import InMemorySignalStore


LOGGER = logging.getLogger(__name__)
OptionChainProvider = Callable[[SignalRecord], Sequence[OptionContractSnapshot]]
ACCOUNT_BALANCE_CACHE_TTL_SECONDS = 30


def _current_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dashboard_sound_file(kind: str) -> Path:
    sound_kind = _dashboard_sound_profile(kind)
    return Path(".local_state") / f"dashboard_{sound_kind}_alert_v5.wav"


def _dashboard_sound_profile(kind: str) -> str:
    return "alert" if kind in {"alert", "test"} else kind


def _dashboard_sound_phrase(kind: str) -> str:
    return "New Proposal"


def _ensure_dashboard_sound_file(kind: str) -> Path:
    path = _dashboard_sound_file(kind)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    sound_kind = _dashboard_sound_profile(kind)
    tones = [(880, 0.72)] if sound_kind == "alert" else [(988, 0.5)]
    gap_seconds = 0.06
    amplitude = 31500
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for frequency, duration_seconds in tones:
            sample_count = int(sample_rate * duration_seconds)
            for index in range(sample_count):
                t = index / sample_rate
                attack = min(1.0, t / 0.03)
                release = min(1.0, max(0.0, (duration_seconds - t) / 0.16))
                envelope = max(0.0, min(attack, release))
                value = math.sin(2 * math.pi * frequency * t)
                harmonic = 0.32 * math.sin(2 * math.pi * frequency * 2 * t)
                lower_harmonic = 0.18 * math.sin(2 * math.pi * (frequency / 2) * t)
                sample = int(amplitude * envelope * ((value + harmonic + lower_harmonic) / 1.5))
                sample = max(-32767, min(32767, sample))
                wav_file.writeframes(struct.pack("<hh", sample, sample))
            wav_file.writeframes(b"\x00\x00\x00\x00" * int(sample_rate * gap_seconds))
    return path


def _speak_dashboard_sound(kind: str) -> None:
    phrase = _dashboard_sound_phrase(kind).replace("'", "''")
    command = (
        "$voice = New-Object -ComObject SAPI.SpVoice; "
        "$voice.Volume = 100; "
        "$voice.Rate = 0; "
        f"$null = $voice.Speak('{phrase}')"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-STA", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
            check=False,
            timeout=8,
        )
    except Exception:
        LOGGER.exception("Dashboard SAPI speech fallback failed")


def _play_dashboard_sound_sequence(kind: str) -> None:
    try:
        import winsound

        path = _ensure_dashboard_sound_file(kind)
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
    except Exception:
        LOGGER.exception("Dashboard WAV sound playback failed; falling back to Windows beep")
        frequency = 1175 if _dashboard_sound_profile(kind) == "alert" else 988
        try:
            import winsound

            winsound.Beep(frequency, 720)
        except Exception:
            LOGGER.exception("Dashboard local sound fallback failed")
    if _dashboard_sound_profile(kind) == "alert":
        _speak_dashboard_sound(kind)


def _start_dashboard_sound(kind: str) -> str:
    if not sys.platform.startswith("win"):
        return "unsupported"
    thread = threading.Thread(target=_play_dashboard_sound_sequence, args=(kind,), daemon=True)
    thread.start()
    return "started"


def create_app(
    config: BridgeConfig | None = None,
    store: InMemorySignalStore | None = None,
    option_chain_provider: OptionChainProvider | None = None,
    proposal_planner: OptionProposalPlanner | None = None,
    schwab_order_client: SchwabMarketDataClient | None = None,
) -> FastAPI:
    bridge_config = config or load_config()
    signal_store = store or InMemorySignalStore(
        max_records=bridge_config.signals.max_recent,
        duplicate_window_seconds=bridge_config.signals.duplicate_window_seconds,
        audit_log_path=bridge_config.storage.signal_audit_path if bridge_config.storage.persist_signals else None,
        proposal_log_path=bridge_config.storage.proposal_audit_path if bridge_config.storage.persist_signals else None,
    )

    resolved_option_chain_provider = option_chain_provider
    if resolved_option_chain_provider is None and bridge_config.options.demo_chain_enabled:
        resolved_option_chain_provider = DemoOptionChainProvider(bridge_config.options)
    if resolved_option_chain_provider is None:
        resolved_option_chain_provider = build_schwab_option_chain_provider(bridge_config)

    app = FastAPI(title="NT to Schwab Bridge", version="0.1.0")
    app.state.config = bridge_config
    app.state.signal_store = signal_store
    app.state.decision_engine = SignalDecisionEngine(bridge_config)
    app.state.option_chain_provider = resolved_option_chain_provider
    app.state.proposal_planner = proposal_planner or OptionProposalPlanner(bridge_config.options)
    app.state.schwab_order_client = schwab_order_client or SchwabMarketDataClient(bridge_config.schwab)
    app.state.account_selection_store = AccountSelectionStore(
        bridge_config.storage.account_selection_path,
        default_selected_ids=[
            account.id for account in bridge_config.schwab.accounts if account.enabled and account.default_selected
        ],
    )
    app.state.dashboard_settings_store = DashboardSettingsStore(bridge_config.storage.dashboard_settings_path)
    app.state.order_audit_store = OrderAuditStore(bridge_config.storage.order_audit_path)
    app.state.schwab_account_discovery_cache = {
        "expires_at": datetime.fromtimestamp(0, tz=timezone.utc),
        "accounts": [],
        "notes": [],
    }
    app.state.schwab_account_balance_cache = {
        "expires_at": datetime.fromtimestamp(0, tz=timezone.utc),
        "account_key": (),
        "balances": {},
        "notes": [],
    }

    def get_config() -> BridgeConfig:
        return app.state.config

    def get_store() -> InMemorySignalStore:
        return app.state.signal_store

    def get_decision_engine() -> SignalDecisionEngine:
        return app.state.decision_engine

    def get_option_chain_provider() -> OptionChainProvider | None:
        provider = app.state.option_chain_provider
        if provider is not None:
            planner_config = get_proposal_planner().config
            if hasattr(provider, "planner_config"):
                provider.planner_config = planner_config
            if hasattr(provider, "config"):
                provider.config = planner_config
        return provider

    def get_proposal_planner() -> OptionProposalPlanner:
        max_loss_dollars = app.state.dashboard_settings_store.get_max_loss_dollars()
        entry_offset_cents = app.state.dashboard_settings_store.get_entry_offset_cents()
        expiry_label = app.state.dashboard_settings_store.get_expiry_label()
        target_percentages = app.state.dashboard_settings_store.get_target_percentages()
        allow_itm = app.state.dashboard_settings_store.get_allow_itm()
        return _proposal_planner_with_dashboard_settings(
            app.state.proposal_planner,
            allow_itm=allow_itm,
            max_loss_dollars=max_loss_dollars,
            entry_offset_cents=entry_offset_cents,
            expiry_label=expiry_label,
            target_percentages=target_percentages,
        )

    def get_schwab_order_client() -> SchwabMarketDataClient:
        return app.state.schwab_order_client

    def get_account_selection_store() -> AccountSelectionStore:
        return app.state.account_selection_store

    def get_dashboard_settings_store() -> DashboardSettingsStore:
        return app.state.dashboard_settings_store

    def get_order_audit_store() -> OrderAuditStore:
        return app.state.order_audit_store

    def get_schwab_accounts() -> tuple[list, list[str]]:
        return _resolve_schwab_accounts(bridge_config, app.state.schwab_account_discovery_cache)

    def get_schwab_account_balances(accounts: list) -> tuple[dict[str, SchwabAccountBalance], list[str]]:
        return _resolve_schwab_account_balances(
            bridge_config,
            accounts,
            app.state.schwab_account_balance_cache,
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(render_dashboard_html())

    @app.post("/dashboard/sound/{kind}")
    async def dashboard_sound(kind: str, cfg: BridgeConfig = Depends(get_config)) -> dict[str, str]:
        if kind not in {"test", "alert"}:
            raise HTTPException(status_code=400, detail="Unsupported dashboard sound kind.")
        if not cfg.dashboard.alerts_enabled or not cfg.dashboard.sound_enabled:
            return {"status": "disabled", "method": "local"}
        status = _start_dashboard_sound(kind)
        return {"status": status, "method": "winsound_wav" if status == "started" else "local"}

    @app.get("/dashboard/settings", response_model=DashboardSettingsResponse)
    async def dashboard_settings(
        settings: DashboardSettingsStore = Depends(get_dashboard_settings_store),
    ) -> DashboardSettingsResponse:
        return DashboardSettingsResponse(
            allow_itm=settings.get_allow_itm(),
            max_loss_dollars=settings.get_max_loss_dollars(),
            max_loss_choices=settings.max_loss_choices,
            entry_offset_cents=settings.get_entry_offset_cents(),
            entry_offset_choices=settings.entry_offset_choices,
            expiry_label=settings.get_expiry_label(),
            expiry_choices=settings.expiry_choices,
            target_percentages=settings.get_target_percentages(),
        )

    @app.post("/dashboard/settings", response_model=DashboardSettingsResponse)
    async def update_dashboard_settings(
        request: DashboardSettingsUpdateRequest,
        settings: DashboardSettingsStore = Depends(get_dashboard_settings_store),
    ) -> DashboardSettingsResponse:
        if request.max_loss_dollars is not None and request.max_loss_dollars not in settings.max_loss_choices:
            raise HTTPException(
                status_code=422,
                detail=f"max_loss_dollars must be one of: {', '.join(str(item) for item in settings.max_loss_choices)}",
            )
        if request.entry_offset_cents is not None and request.entry_offset_cents not in settings.entry_offset_choices:
            raise HTTPException(
                status_code=422,
                detail=f"entry_offset_cents must be one of: {', '.join(str(item) for item in settings.entry_offset_choices)}",
            )
        normalized_expiry_label = (
            request.expiry_label.upper().strip().replace(" ", "_") if request.expiry_label is not None else None
        )
        if normalized_expiry_label is not None and normalized_expiry_label not in settings.expiry_choices:
            raise HTTPException(
                status_code=422,
                detail=f"expiry_label must be one of: {', '.join(settings.expiry_choices)}",
            )
        normalized_target_percentages = None
        if request.target_percentages is not None:
            try:
                normalized_target_percentages = settings.normalize_target_percentages(
                    request.target_percentages,
                    strict=True,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if request.max_loss_dollars is not None:
            settings.set_max_loss_dollars(request.max_loss_dollars)
        if request.entry_offset_cents is not None:
            settings.set_entry_offset_cents(request.entry_offset_cents)
        if request.allow_itm is not None:
            settings.set_allow_itm(request.allow_itm)
        if normalized_expiry_label is not None:
            settings.set_expiry_label(normalized_expiry_label)
        if normalized_target_percentages is not None:
            settings.set_target_percentages(normalized_target_percentages)
        return DashboardSettingsResponse(
            allow_itm=settings.get_allow_itm(),
            max_loss_dollars=settings.get_max_loss_dollars(),
            max_loss_choices=settings.max_loss_choices,
            entry_offset_cents=settings.get_entry_offset_cents(),
            entry_offset_choices=settings.entry_offset_choices,
            expiry_label=settings.get_expiry_label(),
            expiry_choices=settings.expiry_choices,
            target_percentages=settings.get_target_percentages(),
        )

    @app.get("/health", response_model=HealthResponse)
    async def health(
        cfg: BridgeConfig = Depends(get_config),
        signals: InMemorySignalStore = Depends(get_store),
    ) -> HealthResponse:
        return HealthResponse(
            execution_mode=cfg.service.execution_mode,
            allow_live_orders=cfg.service.allow_live_orders,
            signal_count=signals.count(),
            config=cfg.public_status(),
        )

    @app.get("/schwab/status", response_model=SchwabMarketDataStatusResponse)
    async def schwab_status(cfg: BridgeConfig = Depends(get_config)) -> SchwabMarketDataStatusResponse:
        return schwab_market_data_status(cfg)

    @app.get("/schwab/option-chain/check", response_model=SchwabOptionChainCheckResponse)
    async def schwab_option_chain_status(
        symbol: str = Query(default="SPY", min_length=1, max_length=12),
        direction: str = Query(default="long", pattern="^(long|short)$"),
        expiry: str = Query(default="1DTE", min_length=3, max_length=18),
        cfg: BridgeConfig = Depends(get_config),
    ) -> SchwabOptionChainCheckResponse:
        return schwab_option_chain_check(config=cfg, symbol=symbol, direction=direction, expiry_label=expiry)

    @app.get("/schwab/accounts", response_model=AccountSelectionResponse)
    async def schwab_accounts(
        cfg: BridgeConfig = Depends(get_config),
        selections: AccountSelectionStore = Depends(get_account_selection_store),
    ) -> AccountSelectionResponse:
        accounts, notes = get_schwab_accounts()
        balances, balance_notes = get_schwab_account_balances(accounts)
        return _account_selection_response(
            accounts,
            selections.get(),
            [*notes, *balance_notes],
            default_when_empty=not selections.has_saved_selection(),
            balances_by_id=balances,
        )

    @app.post("/schwab/accounts/selection", response_model=AccountSelectionResponse)
    async def update_schwab_account_selection(
        request: AccountSelectionUpdateRequest,
        cfg: BridgeConfig = Depends(get_config),
        selections: AccountSelectionStore = Depends(get_account_selection_store),
    ) -> AccountSelectionResponse:
        accounts, notes = get_schwab_accounts()
        balances, balance_notes = get_schwab_account_balances(accounts)
        known_ids = {account.id for account in accounts if account.enabled}
        selected_ids = [account_id for account_id in request.selected_account_ids if account_id in known_ids]
        selections.set(selected_ids)
        return _account_selection_response(
            accounts,
            selected_ids,
            [*notes, *balance_notes],
            default_when_empty=False,
            balances_by_id=balances,
        )

    @app.post("/signal", response_model=SignalAcceptedResponse, status_code=202)
    async def receive_signal(
        payload: SignalPayload,
        cfg: BridgeConfig = Depends(get_config),
        signals: InMemorySignalStore = Depends(get_store),
        decision_engine: SignalDecisionEngine = Depends(get_decision_engine),
    ) -> SignalAcceptedResponse:
        if payload.symbol not in cfg.signals.allowed_symbols:
            raise HTTPException(
                status_code=422,
                detail=f"Symbol {payload.symbol} is not enabled for this bridge.",
            )

        decision = decision_engine.evaluate(payload)
        result = signals.add(payload, decision=decision, execution_mode=cfg.service.execution_mode)
        record = result.record
        if result.duplicate:
            LOGGER.info("Duplicate signal ignored: id=%s duplicate_of=%s", record.id, record.duplicate_of)
            message = "Duplicate signal received; original signal remains pending."
        elif decision.status == "blocked":
            LOGGER.info(
                "Signal blocked by decision gate: id=%s symbol=%s reasons=%s",
                record.id,
                payload.symbol,
                ",".join(decision.reasons),
            )
            message = "Signal accepted for audit, but blocked by the decision gate."
        else:
            LOGGER.info(
                "Signal accepted: id=%s symbol=%s direction=%s signal_type=%s decision=%s",
                record.id,
                payload.symbol,
                payload.direction,
                payload.signal_type,
                decision.status,
            )
            message = "Signal accepted for dashboard review."

        if not result.duplicate and decision.status != "blocked":
            _generate_and_store_proposals(
                record=record,
                signals=signals,
                provider=get_option_chain_provider(),
                planner=get_proposal_planner(),
            )

        return SignalAcceptedResponse(
            id=record.id,
            status=record.status,
            duplicate=result.duplicate,
            duplicate_of=record.duplicate_of,
            received_at=record.received_at,
            review_status=record.review_status,
            decision=record.decision,
            message=message,
        )

    @app.post("/demo/signal", response_model=SignalAcceptedResponse, status_code=202)
    async def create_demo_signal(
        cfg: BridgeConfig = Depends(get_config),
        signals: InMemorySignalStore = Depends(get_store),
        decision_engine: SignalDecisionEngine = Depends(get_decision_engine),
    ) -> SignalAcceptedResponse:
        if not cfg.options.demo_chain_enabled:
            raise HTTPException(status_code=409, detail="Demo chain is not enabled.")
        symbol = cfg.options.allowed_symbols[0] if cfg.options.allowed_symbols else "SPY"
        payload = SignalPayload(
            signal_id=f"demo-{datetime.now(timezone.utc).timestamp()}",
            strategy="DashboardDemoSignal",
            symbol=symbol,
            direction="long",
            qty=1,
            timeframe=cfg.signals.default_timeframe,
            timestamp=datetime.now(timezone.utc),
            underlying_price=620.0,
            signal_type="demo",
            source_indicator="Demo Chain",
            tags=["demo", "dashboard"],
            notes="Local demo signal for dry-run proposal-card testing.",
        )
        decision = decision_engine.evaluate(payload)
        result = signals.add(payload, decision=decision, execution_mode=cfg.service.execution_mode)
        record = result.record
        if not result.duplicate and decision.status != "blocked":
            _generate_and_store_proposals(
                record=record,
                signals=signals,
                provider=get_option_chain_provider(),
                planner=get_proposal_planner(),
            )
        return SignalAcceptedResponse(
            id=record.id,
            status=record.status,
            duplicate=result.duplicate,
            duplicate_of=record.duplicate_of,
            received_at=record.received_at,
            review_status=record.review_status,
            decision=record.decision,
            message="Demo signal created for dashboard proposal review.",
        )

    @app.post("/signal/preview", response_model=SignalDecision)
    async def preview_signal_decision(
        payload: SignalPayload,
        cfg: BridgeConfig = Depends(get_config),
        decision_engine: SignalDecisionEngine = Depends(get_decision_engine),
    ) -> SignalDecision:
        if payload.symbol not in cfg.signals.allowed_symbols:
            raise HTTPException(
                status_code=422,
                detail=f"Symbol {payload.symbol} is not enabled for this bridge.",
            )
        return decision_engine.evaluate(payload)

    @app.get("/signals", response_model=SignalListResponse)
    async def list_signals(
        signals: InMemorySignalStore = Depends(get_store),
        order_audit: OrderAuditStore = Depends(get_order_audit_store),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> SignalListResponse:
        records = signals.list_recent(limit=limit)
        total_count = signals.count()
        return SignalListResponse(
            count=total_count,
            returned_count=len(records),
            total_count=total_count,
            limit=limit,
            signals=_records_with_available_proposal_counts(records, signals=signals, order_audit=order_audit),
        )

    @app.delete("/signals", response_model=SignalClearResponse)
    async def clear_signals(
        signals: InMemorySignalStore = Depends(get_store),
    ) -> SignalClearResponse:
        audit_log_configured = signals.audit_log_path is not None
        cleared_count = signals.clear(clear_audit_log=True)
        return SignalClearResponse(cleared_count=cleared_count, audit_log_cleared=audit_log_configured)

    @app.get("/signals/{signal_id}", response_model=SignalRecord)
    async def get_signal(
        signal_id: str,
        signals: InMemorySignalStore = Depends(get_store),
    ) -> SignalRecord:
        record = signals.get(signal_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Signal not found.")
        return record

    @app.get("/signals/{signal_id}/proposals", response_model=OptionProposalResult)
    async def get_signal_proposals(
        signal_id: str,
        signals: InMemorySignalStore = Depends(get_store),
        order_audit: OrderAuditStore = Depends(get_order_audit_store),
    ) -> OptionProposalResult:
        record = signals.get(signal_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Signal not found.")
        result = signals.get_proposals(signal_id)
        if result is not None:
            return result
        audit_result = _proposal_result_from_order_audit(order_audit, signal_id)
        if audit_result is not None:
            return audit_result
        return OptionProposalResult(
            signal_id=signal_id,
            generated_at=datetime.now(timezone.utc),
            blocked_reasons=["proposals_not_generated"],
        )

    @app.post("/signals/{signal_id}/proposals/refresh", response_model=OptionProposalResult)
    async def refresh_signal_proposals(
        signal_id: str,
        signals: InMemorySignalStore = Depends(get_store),
        provider: OptionChainProvider | None = Depends(get_option_chain_provider),
        planner: OptionProposalPlanner = Depends(get_proposal_planner),
    ) -> OptionProposalResult:
        record = signals.get(signal_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Signal not found.")
        result = _build_proposal_result(record=record, provider=provider, planner=planner)
        signals.save_proposals(signal_id, result, preserve_existing_successful=True)
        return result

    @app.post(
        "/signals/{signal_id}/proposals/{proposal_id}/send",
        response_model=ProposalSendResponse,
    )
    async def send_signal_proposal(
        signal_id: str,
        proposal_id: str,
        request: ProposalSendRequest,
        cfg: BridgeConfig = Depends(get_config),
        signals: InMemorySignalStore = Depends(get_store),
        selections: AccountSelectionStore = Depends(get_account_selection_store),
        settings: DashboardSettingsStore = Depends(get_dashboard_settings_store),
        order_client: SchwabMarketDataClient = Depends(get_schwab_order_client),
        order_audit: OrderAuditStore = Depends(get_order_audit_store),
    ) -> ProposalSendResponse:
        record = signals.get(signal_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Signal not found.")
        result = signals.get_proposals(signal_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Proposal result not found.")
        proposal = next((item for item in result.proposals if item.id == proposal_id), None)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposal not found.")

        accounts, _account_notes = get_schwab_accounts()
        known_ids = {account.id for account in accounts if account.enabled}
        selected_account_ids = [account_id for account_id in request.selected_account_ids if account_id in known_ids]
        selections.set(selected_account_ids)
        send_proposal = _proposal_with_quantity_override(
            proposal,
            quantity=request.quantity,
            limit_price=request.limit_price,
            target_percentages=settings.get_target_percentages(),
        )
        return _send_proposal_response(
            cfg=cfg,
            accounts=accounts,
            signal_id=signal_id,
            proposal=send_proposal,
            selected_account_ids=selected_account_ids,
            confirm_live_order=request.confirm_live_order,
            limit_price=request.limit_price,
            order_note=request.order_note or _default_order_note(record, send_proposal),
            order_client=order_client,
            order_audit=order_audit,
        )

    @app.get(
        "/signals/{signal_id}/proposals/{proposal_id}/orders/status",
        response_model=ProposalOrderStatusResponse,
    )
    async def signal_proposal_order_status(
        signal_id: str,
        proposal_id: str,
        signals: InMemorySignalStore = Depends(get_store),
        order_client: SchwabMarketDataClient = Depends(get_schwab_order_client),
        order_audit: OrderAuditStore = Depends(get_order_audit_store),
    ) -> ProposalOrderStatusResponse:
        record = signals.get(signal_id)
        proposal = _proposal_for_status_lookup(signals, order_audit, signal_id, proposal_id)
        if proposal is None:
            if record is None:
                raise HTTPException(status_code=404, detail="Signal not found.")
            raise HTTPException(status_code=404, detail="Proposal not found.")
        accounts, _account_notes = get_schwab_accounts()
        return _proposal_order_status_response(
            signal_id=signal_id,
            proposal=proposal,
            accounts=accounts,
            order_client=order_client,
            order_audit=order_audit,
        )

    @app.post(
        "/signals/{signal_id}/proposals/{proposal_id}/targets/{target_index}/send",
        response_model=ProposalSendResponse,
    )
    async def send_signal_proposal_target(
        signal_id: str,
        proposal_id: str,
        target_index: int,
        request: ProposalExitSendRequest,
        cfg: BridgeConfig = Depends(get_config),
        signals: InMemorySignalStore = Depends(get_store),
        selections: AccountSelectionStore = Depends(get_account_selection_store),
        order_client: SchwabMarketDataClient = Depends(get_schwab_order_client),
        order_audit: OrderAuditStore = Depends(get_order_audit_store),
    ) -> ProposalSendResponse:
        if target_index < 0:
            raise HTTPException(status_code=400, detail="Target index must be non-negative.")
        record = signals.get(signal_id)
        proposal = _proposal_for_status_lookup(signals, order_audit, signal_id, proposal_id)
        if proposal is None:
            if record is None:
                raise HTTPException(status_code=404, detail="Signal not found.")
            raise HTTPException(status_code=404, detail="Proposal not found.")
        if target_index >= len(proposal.exit_targets):
            raise HTTPException(status_code=404, detail="Exit target not found.")

        accounts, _account_notes = get_schwab_accounts()
        known_ids = {account.id for account in accounts if account.enabled}
        selected_account_ids = [account_id for account_id in request.selected_account_ids if account_id in known_ids]
        selections.set(selected_account_ids)
        order_status = _proposal_order_status_response(
            signal_id=signal_id,
            proposal=proposal,
            accounts=accounts,
            order_client=order_client,
            order_audit=order_audit,
        )
        return _send_proposal_exit_response(
            cfg=cfg,
            accounts=accounts,
            signal_id=signal_id,
            proposal=proposal,
            target_index=target_index,
            selected_account_ids=selected_account_ids,
            confirm_live_order=request.confirm_live_order,
            order_note=request.order_note or _default_exit_order_note_for_record(record, proposal, target_index),
            order_status=order_status,
            order_client=order_client,
            order_audit=order_audit,
        )

    @app.post("/signals/{signal_id}/review", response_model=SignalRecord)
    async def mark_signal_reviewed(
        signal_id: str,
        signals: InMemorySignalStore = Depends(get_store),
    ) -> SignalRecord:
        record = signals.mark_reviewed(signal_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Signal not found.")
        return record

    @app.get("/dashboard/summary", response_model=DashboardSummaryResponse)
    async def dashboard_summary(
        cfg: BridgeConfig = Depends(get_config),
        signals: InMemorySignalStore = Depends(get_store),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> DashboardSummaryResponse:
        records = signals.list_recent(limit=limit)
        decision_counts = Counter(record.decision.status if record.decision else "unknown" for record in records)
        review_status_counts = Counter(record.review_status for record in records)
        duplicate_count = sum(1 for record in records if record.status == "duplicate")
        return DashboardSummaryResponse(
            signal_count=signals.count(),
            recent_count=len(records),
            duplicate_count=duplicate_count,
            decision_counts=dict(decision_counts),
            review_status_counts=dict(review_status_counts),
            latest_signal=records[0] if records else None,
            config=cfg.public_status(),
        )

    return app


def _generate_and_store_proposals(
    record: SignalRecord,
    signals: InMemorySignalStore,
    provider: OptionChainProvider | None,
    planner: OptionProposalPlanner,
) -> OptionProposalResult | None:
    if provider is None:
        return None
    result = _build_proposal_result(record=record, provider=provider, planner=planner)
    signals.save_proposals(record.id, result)
    return result


def _proposal_planner_with_dashboard_settings(
    base_planner: OptionProposalPlanner,
    *,
    allow_itm: bool,
    max_loss_dollars: int,
    entry_offset_cents: int,
    expiry_label: str,
    target_percentages: list[float],
) -> OptionProposalPlanner:
    config = base_planner.config.model_copy(
        update={
            "allow_in_the_money_primary": allow_itm,
            "exit_target_percentages": target_percentages,
            "expiries": [expiry_label],
            "marketable_limit_offset": round(entry_offset_cents / 100, 2),
            "min_debit_per_trade": 0,
            "max_debit_per_trade": float(max_loss_dollars),
        }
    )
    return OptionProposalPlanner(config)


def _build_proposal_result(
    record: SignalRecord,
    provider: OptionChainProvider | None,
    planner: OptionProposalPlanner,
) -> OptionProposalResult:
    generated_at = _current_utc()
    if provider is None:
        return OptionProposalResult(
            signal_id=record.id,
            generated_at=generated_at,
            source=_proposal_source(provider),
            blocked_reasons=["proposal_provider_not_configured"],
        )
    session_block_reason = _regular_options_session_block_reason(provider, planner, generated_at)
    if session_block_reason is not None:
        return OptionProposalResult(
            signal_id=record.id,
            generated_at=generated_at,
            source=_proposal_source(provider),
            blocked_reasons=[session_block_reason],
        )
    try:
        planning_record = _record_for_option_planning(record, planner)
        chain = list(provider(planning_record))
        underlying_price = getattr(provider, "last_underlying_price", None)
        result = planner.plan(planning_record, chain, as_of=generated_at, underlying_price=underlying_price)
        return result.model_copy(update={"source": _proposal_source(provider)})
    except Exception as exc:
        LOGGER.exception("Proposal generation failed: signal_id=%s", record.id)
        return OptionProposalResult(
            signal_id=record.id,
            generated_at=generated_at,
            source=_proposal_source(provider),
            blocked_reasons=[f"proposal_generation_error:{exc.__class__.__name__}"],
        )


def _regular_options_session_block_reason(
    provider: OptionChainProvider | None,
    planner: OptionProposalPlanner,
    as_of: datetime,
) -> str | None:
    if _proposal_provider_kind(provider) != "schwab":
        return None
    return planner.config.regular_options_session_block_reason(as_of)


def _proposal_provider_kind(provider: OptionChainProvider | None) -> str:
    if provider is None:
        return "none"
    kind = getattr(provider, "provider_kind", None)
    if kind not in {"demo", "schwab", "injected", "unknown"}:
        return "injected"
    return str(kind)


def _proposal_source(provider: OptionChainProvider | None) -> OptionProposalSource:
    if provider is None:
        return OptionProposalSource(
            kind="none",
            name="none",
            notes=["No option-chain provider is configured."],
        )
    kind = _proposal_provider_kind(provider)
    name = str(getattr(provider, "provider_name", "") or provider.__class__.__name__ or kind)
    notes = getattr(provider, "provider_notes", [])
    if not isinstance(notes, list):
        notes = [str(notes)]
    return OptionProposalSource(
        kind=kind,
        name=name,
        read_only=True,
        live_orders_enabled=False,
        notes=[str(note) for note in notes],
    )


def _record_for_option_planning(record: SignalRecord, planner: OptionProposalPlanner) -> SignalRecord:
    source_symbol = record.payload.symbol.upper()
    option_symbol = planner.config.option_symbol_for(source_symbol)
    if option_symbol == source_symbol:
        return record
    payload = record.payload.model_copy(
        update={
            "symbol": option_symbol,
            "underlying_price": None,
            "tags": list(dict.fromkeys([*record.payload.tags, f"trigger:{source_symbol}", f"option:{option_symbol}"])),
            "notes": _append_note(record.payload.notes, f"Option planner mapped trigger symbol {source_symbol} to {option_symbol}."),
        }
    )
    return record.model_copy(update={"payload": payload})


def _append_note(existing: str, addition: str) -> str:
    if existing.strip():
        return f"{existing.strip()} {addition}"
    return addition


def _resolve_schwab_accounts(config: BridgeConfig, cache: dict) -> tuple[list, list[str]]:
    configured_accounts = [account for account in config.schwab.accounts if account.enabled]
    discovery_notes: list[str] = []
    discovered_accounts: list = []
    if config.schwab.account_discovery_enabled:
        now = datetime.now(timezone.utc)
        expires_at = cache.get("expires_at")
        if not isinstance(expires_at, datetime) or expires_at <= now:
            discovered_accounts, discovery_notes = discover_schwab_accounts(config)
            cache["accounts"] = discovered_accounts
            cache["notes"] = discovery_notes
            ttl_seconds = 0 if _has_schwab_auth_discovery_failure(discovery_notes) else config.schwab.account_discovery_ttl_seconds
            cache["expires_at"] = now + timedelta(seconds=ttl_seconds)
        else:
            discovered_accounts = list(cache.get("accounts") or [])
            discovery_notes = list(cache.get("notes") or [])
        if not discovered_accounts:
            return [], discovery_notes
        return _merge_account_configs(configured_accounts, discovered_accounts), discovery_notes
    return _merge_account_configs(configured_accounts, []), discovery_notes


def _resolve_schwab_account_balances(
    config: BridgeConfig,
    accounts: list,
    cache: dict,
) -> tuple[dict[str, SchwabAccountBalance], list[str]]:
    eligible_accounts = [
        account
        for account in accounts
        if getattr(account, "enabled", False) and str(getattr(account, "account_hash", "") or "").strip()
    ]
    if not eligible_accounts:
        return {}, []
    if not config.schwab.market_data_enabled:
        return {}, []
    if not (config.schwab.token_store_path or config.schwab.access_token or config.schwab.refresh_token):
        return {}, ["Schwab account balances require a configured Schwab token source."]

    now = _current_utc()
    account_key = tuple((account.id, getattr(account, "account_hash", "")) for account in eligible_accounts)
    expires_at = cache.get("expires_at")
    if (
        isinstance(expires_at, datetime)
        and expires_at > now
        and cache.get("account_key") == account_key
    ):
        return dict(cache.get("balances") or {}), list(cache.get("notes") or [])

    client = SchwabMarketDataClient(config.schwab)
    balances: dict[str, SchwabAccountBalance] = {}
    notes: list[str] = []
    for account in eligible_accounts:
        try:
            summary = client.get_account_balance_summary(account.account_hash)
            balances[account.id] = SchwabAccountBalance(
                available_to_trade=summary.get("available_to_trade"),
                buying_power=summary.get("buying_power"),
                cash_balance=summary.get("cash_balance"),
                source=str(summary.get("source", "") or ""),
                updated_at=now,
            )
        except (SchwabApiError, SchwabOAuthError) as exc:
            balances[account.id] = SchwabAccountBalance(updated_at=now, error=str(exc))
            label = account.label or account.account_number or account.id
            notes.append(f"Schwab balance lookup failed for {label}: {exc}")

    cache["expires_at"] = now + timedelta(seconds=ACCOUNT_BALANCE_CACHE_TTL_SECONDS)
    cache["account_key"] = account_key
    cache["balances"] = balances
    cache["notes"] = notes
    return dict(balances), list(notes)


def _has_schwab_auth_discovery_failure(notes: list[str]) -> bool:
    normalized = " ".join(notes).lower()
    return bool(
        normalized
        and any(marker in normalized for marker in ("auth", "token", "expired", "login", "refresh"))
        and any(marker in normalized for marker in ("failed", "required", "expired", "login"))
    )


def _merge_account_configs(configured_accounts: list, discovered_accounts: list) -> list:
    if discovered_accounts:
        return [account for account in discovered_accounts if account.enabled]

    merged: list = []
    seen_ids: set[str] = set()
    discovered_by_hash = {
        account.account_hash: account
        for account in discovered_accounts
        if getattr(account, "account_hash", "")
    }
    discovered_by_number = {
        account.account_number: account
        for account in discovered_accounts
        if getattr(account, "account_number", "")
    }
    for account in configured_accounts:
        discovered = discovered_by_hash.get(account.account_hash) or discovered_by_number.get(account.account_number)
        merged_account = discovered or account
        if merged_account.id not in seen_ids:
            merged.append(merged_account)
            seen_ids.add(merged_account.id)
    for account in discovered_accounts:
        if account.id not in seen_ids:
            merged.append(account)
            seen_ids.add(account.id)
    return merged


def _account_selection_response(
    accounts_config: list,
    selected_account_ids: list[str],
    notes: list[str],
    default_when_empty: bool = True,
    balances_by_id: dict[str, SchwabAccountBalance] | None = None,
) -> AccountSelectionResponse:
    balances_by_id = balances_by_id or {}
    accounts = [_account_route(account, balances_by_id.get(account.id)) for account in accounts_config if account.enabled]
    known_ids = {account.id for account in accounts}
    has_stale_selection = any(account_id not in known_ids for account_id in selected_account_ids)
    selected = [account_id for account_id in selected_account_ids if account_id in known_ids]
    if accounts and (default_when_empty and not selected or has_stale_selection and not selected):
        selected = [account.id for account in accounts]
    response_notes = list(notes)
    if not accounts:
        response_notes.append("No Schwab accounts are configured or discovered for dashboard routing.")
    return AccountSelectionResponse(accounts=accounts, selected_account_ids=selected, notes=response_notes)


def _account_route(account, balance: SchwabAccountBalance | None = None) -> SchwabAccountRoute:
    return SchwabAccountRoute(
        id=account.id,
        label=account.label or account.id,
        account_number=getattr(account, "account_number", ""),
        source=getattr(account, "source", "configured"),
        account_type=account.account_type,
        supports_spreads=account.supports_spreads,
        enabled=account.enabled,
        order_configured=bool(account.account_hash),
        balance=balance,
    )


def _proposal_with_quantity_override(
    proposal: OptionProposal,
    *,
    quantity: int | None,
    limit_price: float | None = None,
    target_percentages: list[float] | None = None,
) -> OptionProposal:
    resolved_quantity = max(1, int(quantity or proposal.quantity))
    send_limit_price = limit_price
    if send_limit_price is None:
        send_limit_price = proposal.send_limit_price
    if send_limit_price is None and proposal.quantity > 0:
        send_limit_price = proposal.debit / (proposal.quantity * 100)
    if send_limit_price is None:
        send_limit_price = proposal.natural_limit_price
    send_limit_price = round(float(send_limit_price or 0), 2)

    natural_limit_price = proposal.natural_limit_price or send_limit_price
    natural_debit = round(natural_limit_price * 100 * resolved_quantity, 2)
    debit = round(send_limit_price * 100 * resolved_quantity, 2)
    legs = [leg.model_copy(update={"qty": resolved_quantity}) for leg in proposal.legs]
    strikes = [leg.strike for leg in proposal.legs]
    right = proposal.legs[0].right if proposal.legs else "CALL"
    structure = "VERTICAL" if proposal.structure == "debit_vertical" else "SINGLE"
    net_delta = None
    if proposal.net_delta is not None and proposal.quantity > 0:
        net_delta = round((proposal.net_delta / proposal.quantity) * resolved_quantity, 4)

    return proposal.model_copy(
        update={
            "quantity": resolved_quantity,
            "legs": legs,
            "debit": debit,
            "max_loss": debit,
            "natural_debit": natural_debit,
            "send_limit_price": send_limit_price,
            "net_delta": net_delta,
            "tos_order_line": _tos_order_line_for_proposal(
                proposal,
                resolved_quantity,
                send_limit_price,
                structure=structure,
                strikes=strikes,
                right=right,
            ),
            "exit_targets": _exit_targets_for_quantity_override(
                proposal,
                resolved_quantity,
                send_limit_price,
                target_percentages=target_percentages,
            ),
        }
    )


def _exit_targets_for_quantity_override(
    proposal: OptionProposal,
    quantity: int,
    entry_limit_price: float,
    *,
    target_percentages: list[float] | None,
) -> list[OptionProposalExitTarget]:
    percentages = [float(value) for value in target_percentages or [] if float(value) > 0]
    if not percentages:
        percentages = [target.target_percent for target in proposal.exit_targets if target.target_percent > 0]
    if not percentages:
        percentages = [20.0, 40.0, 50.0]
    percentages = percentages[: max(1, min(quantity, 3))]

    targets: list[OptionProposalExitTarget] = []
    remaining = quantity
    for index, target_percent in enumerate(percentages):
        target_qty = remaining if index == len(percentages) - 1 else 1
        remaining -= target_qty
        target_limit = round(entry_limit_price * (1 + target_percent / 100), 2)
        if proposal.structure == "debit_vertical" and proposal.width:
            target_limit = min(target_limit, round(float(proposal.width), 2))
        estimated_profit = round(max(0.0, (target_limit - entry_limit_price) * 100 * target_qty), 2)
        targets.append(
            OptionProposalExitTarget(
                qty=target_qty,
                target_percent=target_percent,
                entry_limit_price=entry_limit_price,
                target_limit_price=target_limit,
                estimated_profit=estimated_profit,
                tos_exit_order_line=_tos_exit_order_line_for_proposal(proposal, target_qty, target_limit),
            )
        )
    return targets


def _send_proposal_response(
    *,
    cfg: BridgeConfig,
    accounts: list,
    signal_id: str,
    proposal: OptionProposal,
    selected_account_ids: list[str],
    confirm_live_order: bool = False,
    limit_price: float | None = None,
    order_client: SchwabMarketDataClient | None = None,
    order_note: str = "",
    order_audit: OrderAuditStore | None = None,
) -> ProposalSendResponse:
    accounts_by_id = {account.id: account for account in accounts if account.enabled}
    account_results: list[ProposalAccountSendResult] = []
    order_payload = _schwab_order_payload(proposal, limit_price=limit_price)
    if not selected_account_ids:
        _append_order_audit_event(
            order_audit,
            signal_id=signal_id,
            proposal=proposal,
            selected_account_ids=[],
            result=None,
            order_note=order_note,
            reasons=["no_selected_accounts"],
        )
        return ProposalSendResponse(
            status="blocked",
            signal_id=signal_id,
            proposal_id=proposal.id,
            selected_account_ids=[],
            order_note=order_note,
            notes=["Select at least one Schwab account before sending a proposal."],
        )

    for account_id in selected_account_ids:
        account = accounts_by_id.get(account_id)
        if account is None:
            continue
        reasons: list[str] = []
        if proposal.structure == "debit_vertical" and not account.supports_spreads:
            reasons.append("account_not_spread_approved")
        if not account.account_hash:
            reasons.append("account_hash_missing")
        live_gate_open = (
            cfg.service.execution_mode == "live"
            and cfg.service.allow_live_orders
            and cfg.risk.trading_enabled
        )
        if not live_gate_open:
            reasons.append("live_orders_blocked")
        elif not confirm_live_order:
            reasons.append("live_order_confirmation_required")
        if any(reason not in {"live_orders_blocked", "live_order_confirmation_required"} for reason in reasons):
            status = "blocked"
        elif live_gate_open and confirm_live_order:
            try:
                placement = (order_client or SchwabMarketDataClient(cfg.schwab)).place_order(
                    account.account_hash,
                    order_payload,
                )
                result = ProposalAccountSendResult(
                    account_id=account.id,
                    account_label=account.label or account.id,
                    status="submitted",
                    reasons=["schwab_order_submitted"],
                    broker_order_id=str(placement.get("broker_order_id") or "") or None,
                    order_payload=order_payload,
                    order_note=order_note,
                )
                account_results.append(result)
                _append_order_audit_event(
                    order_audit,
                    signal_id=signal_id,
                    proposal=proposal,
                    selected_account_ids=selected_account_ids,
                    result=result,
                    order_note=order_note,
                )
                continue
            except (SchwabApiError, RuntimeError) as exc:
                result = ProposalAccountSendResult(
                    account_id=account.id,
                    account_label=account.label or account.id,
                    status="blocked",
                    reasons=[f"schwab_order_submit_failed:{exc}"],
                    order_payload=order_payload,
                    order_note=order_note,
                )
                account_results.append(result)
                _append_order_audit_event(
                    order_audit,
                    signal_id=signal_id,
                    proposal=proposal,
                    selected_account_ids=selected_account_ids,
                    result=result,
                    order_note=order_note,
                )
                continue
        else:
            status = "dry_run" if "live_orders_blocked" in reasons else "blocked"
        result = ProposalAccountSendResult(
            account_id=account.id,
            account_label=account.label or account.id,
            status=status,
            reasons=list(dict.fromkeys(reasons or ["order_payload_ready"])),
            order_payload=order_payload if status != "blocked" else None,
            order_note=order_note,
        )
        account_results.append(result)
        _append_order_audit_event(
            order_audit,
            signal_id=signal_id,
            proposal=proposal,
            selected_account_ids=selected_account_ids,
            result=result,
            order_note=order_note,
        )

    status = _aggregate_send_status(account_results)
    notes = [_send_response_note(status)]
    return ProposalSendResponse(
        status=status,
        signal_id=signal_id,
        proposal_id=proposal.id,
        selected_account_ids=selected_account_ids,
        account_results=account_results,
        order_note=order_note,
        notes=notes,
    )


def _proposal_for_status_lookup(
    signals: InMemorySignalStore,
    order_audit: OrderAuditStore,
    signal_id: str,
    proposal_id: str,
) -> OptionProposal | None:
    if _submitted_entry_events_by_account(order_audit, signal_id, proposal_id):
        audit_proposal = _proposal_from_order_audit(order_audit, signal_id, proposal_id)
        if audit_proposal is not None:
            return audit_proposal
    result = signals.get_proposals(signal_id)
    if result is not None:
        proposal = next((item for item in result.proposals if item.id == proposal_id), None)
        if proposal is not None:
            return proposal
    return _proposal_from_order_audit(order_audit, signal_id, proposal_id)


def _records_with_available_proposal_counts(
    records: list[SignalRecord],
    *,
    signals: InMemorySignalStore,
    order_audit: OrderAuditStore | None,
) -> list[SignalRecord]:
    counted_records: list[SignalRecord] = []
    for record in records:
        stored_result = signals.get_proposals(record.id)
        stored_count = len(stored_result.proposals) if stored_result is not None else record.proposal_count
        audit_result = _proposal_result_from_order_audit(order_audit, record.id)
        audit_count = len(audit_result.proposals) if audit_result is not None else 0
        proposal_count = max(record.proposal_count, stored_count, audit_count)
        if proposal_count == record.proposal_count:
            counted_records.append(record)
        else:
            counted_records.append(record.model_copy(update={"proposal_count": proposal_count}))
    return counted_records


def _proposal_result_from_order_audit(
    order_audit: OrderAuditStore | None,
    signal_id: str,
) -> OptionProposalResult | None:
    proposal = _proposal_from_order_audit(order_audit, signal_id)
    if proposal is None:
        return None
    return OptionProposalResult(
        signal_id=signal_id,
        generated_at=datetime.now(timezone.utc),
        source=OptionProposalSource(
            kind="schwab",
            name="Schwab order audit",
            read_only=False,
            live_orders_enabled=True,
            notes=["Restored from a submitted Schwab order audit record."],
        ),
        proposals=[proposal],
        eligible_contract_count=1,
        blocked_reasons=[],
    )


def _proposal_from_order_audit(
    order_audit: OrderAuditStore | None,
    signal_id: str,
    proposal_id: str | None = None,
) -> OptionProposal | None:
    events = _proposal_send_events(order_audit, signal_id=signal_id, proposal_id=proposal_id)
    if not events:
        return None
    submitted_events = [event for event in events if event.get("status") == "submitted"]
    seed = _latest_audit_event(submitted_events or events)
    if seed is None:
        return None
    legs = _proposal_legs_from_order_audit(seed)
    if not legs:
        return None
    quantity = max(1, int(_to_float(seed.get("quantity")) or legs[0].qty))
    send_limit = _to_float_or_none(seed.get("send_limit_price"))
    if send_limit is None:
        payload = seed.get("order_payload")
        if isinstance(payload, dict):
            send_limit = _to_float_or_none(payload.get("price"))
    natural_limit = _to_float(seed.get("natural_limit_price"))
    entry_limit = send_limit if send_limit is not None else natural_limit
    debit = round(entry_limit * 100 * quantity, 2) if entry_limit > 0 else _to_float(seed.get("natural_debit"))
    exit_targets = _proposal_exit_targets_from_order_audit(seed, quantity, entry_limit)
    created_at = _parse_audit_datetime(seed.get("created_at")) or datetime.now(timezone.utc)
    return OptionProposal(
        id=str(seed.get("proposal_id") or proposal_id or ""),
        signal_id=signal_id,
        symbol=str(seed.get("symbol") or legs[0].symbol).upper(),
        direction="short" if str(seed.get("direction")).lower() == "short" else "long",
        structure="debit_vertical" if seed.get("structure") == "debit_vertical" else "single",
        status="proposed",
        created_at=created_at,
        expiry=_parse_audit_date(seed.get("expiry")) or legs[0].expiry,
        quantity=quantity,
        legs=legs,
        debit=debit,
        max_loss=debit,
        natural_limit_price=natural_limit,
        natural_debit=_to_float(seed.get("natural_debit")),
        send_limit_price=send_limit,
        price_protection=str(seed.get("price_protection") or ""),
        tos_order_line=str(seed.get("tos_order_line") or ""),
        exit_targets=exit_targets,
        reasons=[],
        notes=["Restored from submitted Schwab order audit; use Get Order Info to refresh actual fill."],
        dry_run=seed.get("status") != "submitted",
    )


def _proposal_send_events(
    order_audit: OrderAuditStore | None,
    *,
    signal_id: str,
    proposal_id: str | None = None,
) -> list[dict]:
    if order_audit is None:
        return []
    events: list[dict] = []
    for event in order_audit.list_events():
        if event.get("event_type") != "proposal_send":
            continue
        if event.get("signal_id") != signal_id:
            continue
        if proposal_id is not None and event.get("proposal_id") != proposal_id:
            continue
        events.append(event)
    return events


def _latest_audit_event(events: list[dict]) -> dict | None:
    if not events:
        return None
    return max(events, key=lambda event: str(event.get("created_at") or ""))


def _proposal_legs_from_order_audit(event: dict) -> list[OptionProposalLeg]:
    payload = event.get("order_payload")
    if not isinstance(payload, dict):
        return []
    raw_legs = payload.get("orderLegCollection")
    if not isinstance(raw_legs, list):
        return []
    event_symbol = str(event.get("symbol") or "").upper()
    event_expiry = _parse_audit_date(event.get("expiry"))
    event_price = _to_float_or_none(event.get("natural_limit_price"))
    if event_price is None:
        event_price = _to_float_or_none(payload.get("price")) or 0.0
    legs: list[OptionProposalLeg] = []
    for raw_leg in raw_legs:
        if not isinstance(raw_leg, dict):
            continue
        instrument = raw_leg.get("instrument")
        if not isinstance(instrument, dict):
            continue
        broker_symbol = str(instrument.get("symbol") or "").strip()
        parsed = _parse_broker_option_symbol(broker_symbol)
        if parsed is None and not (event_symbol and event_expiry):
            continue
        symbol, expiry, right, strike = parsed or (
            event_symbol,
            event_expiry,
            "PUT" if str(event.get("direction") or "").lower() == "short" else "CALL",
            0.0,
        )
        if expiry is None or strike <= 0:
            continue
        instruction = str(raw_leg.get("instruction") or "").upper()
        action = "SELL" if instruction.startswith("SELL") else "BUY"
        legs.append(
            OptionProposalLeg(
                action=action,
                qty=max(1, int(_to_float(raw_leg.get("quantity")) or _to_float(event.get("quantity")) or 1)),
                symbol=symbol,
                broker_symbol=broker_symbol,
                expiry=expiry,
                strike=strike,
                right=right,
                price=event_price,
            )
        )
    return legs


def _parse_broker_option_symbol(value: str) -> tuple[str, date, str, float] | None:
    match = re.match(r"^(.{1,6})(\d{6})([CP])(\d{8})$", value)
    if match is None:
        return None
    symbol = match.group(1).strip().upper()
    try:
        expiry = datetime.strptime(match.group(2), "%y%m%d").date()
    except ValueError:
        return None
    right = "CALL" if match.group(3) == "C" else "PUT"
    strike = int(match.group(4)) / 1000
    return symbol, expiry, right, strike


def _proposal_exit_targets_from_order_audit(
    event: dict,
    quantity: int,
    entry_limit: float,
) -> list[OptionProposalExitTarget]:
    raw_targets = event.get("exit_targets")
    if isinstance(raw_targets, list) and raw_targets:
        try:
            return [OptionProposalExitTarget.model_validate(target) for target in raw_targets if isinstance(target, dict)]
        except ValueError:
            pass
    target_price = round(entry_limit * 1.2, 2) if entry_limit > 0 else 0.0
    estimated_profit = round(max(0.0, (target_price - entry_limit) * 100 * quantity), 2)
    return [
        OptionProposalExitTarget(
            qty=quantity,
            target_percent=20,
            entry_limit_price=entry_limit,
            target_limit_price=target_price,
            estimated_profit=estimated_profit,
        )
    ]


def _parse_audit_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_audit_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _proposal_order_status_response(
    *,
    signal_id: str,
    proposal: OptionProposal,
    accounts: list,
    order_client: SchwabMarketDataClient,
    order_audit: OrderAuditStore,
) -> ProposalOrderStatusResponse:
    submitted_by_account = _submitted_entry_events_by_account(order_audit, signal_id, proposal.id)
    statuses: list[ProposalOrderFillAccountStatus] = []
    for account in accounts:
        event = submitted_by_account.get(account.id)
        if not event:
            continue
        broker_order_id = str(event.get("broker_order_id") or "").strip()
        if not broker_order_id:
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account.id,
                    account_label=account.label or account.id,
                    status="unknown",
                    order_payload=event.get("order_payload") if isinstance(event.get("order_payload"), dict) else None,
                    notes=["Submitted entry audit exists, but no Schwab order id was recorded."],
                )
            )
            continue
        if not account.account_hash:
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account.id,
                    account_label=account.label or account.id,
                    broker_order_id=broker_order_id,
                    status="error",
                    order_payload=event.get("order_payload") if isinstance(event.get("order_payload"), dict) else None,
                    notes=["Account hash is missing; cannot query Schwab order status."],
                )
            )
            continue
        try:
            order = order_client.get_order(account.account_hash, broker_order_id)
            fill = _extract_schwab_fill(order, proposal)
            exit_targets = _exit_target_previews(proposal, fill["average_fill_price"], fill["filled_quantity"])
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account.id,
                    account_label=account.label or account.id,
                    broker_order_id=broker_order_id,
                    status=fill["status"],
                    schwab_status=fill["schwab_status"],
                    filled_quantity=fill["filled_quantity"],
                    remaining_quantity=fill["remaining_quantity"],
                    average_fill_price=fill["average_fill_price"],
                    order_payload=event.get("order_payload") if isinstance(event.get("order_payload"), dict) else None,
                    exit_targets=exit_targets,
                    notes=fill["notes"],
                )
            )
        except (SchwabApiError, RuntimeError) as exc:
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account.id,
                    account_label=account.label or account.id,
                    broker_order_id=broker_order_id,
                    status="error",
                    order_payload=event.get("order_payload") if isinstance(event.get("order_payload"), dict) else None,
                    notes=[f"Schwab order status lookup failed: {exc}"],
                )
            )
    notes: list[str] = []
    if not statuses:
        notes.append("No submitted Schwab entry orders were found in the local order audit for this proposal.")
    return ProposalOrderStatusResponse(
        signal_id=signal_id,
        proposal_id=proposal.id,
        generated_at=datetime.now(timezone.utc),
        account_statuses=statuses,
        has_filled_accounts=any(status.status in {"filled", "partial"} and status.average_fill_price for status in statuses),
        notes=notes,
    )


def _submitted_entry_events_by_account(
    order_audit: OrderAuditStore | None,
    signal_id: str,
    proposal_id: str,
) -> dict[str, dict]:
    if order_audit is None:
        return {}
    events = order_audit.list_events()
    latest: dict[str, dict] = {}
    for event in events:
        if event.get("event_type") != "proposal_send":
            continue
        if event.get("signal_id") != signal_id or event.get("proposal_id") != proposal_id:
            continue
        if event.get("status") != "submitted" or not event.get("broker_order_id"):
            continue
        account_id = str(event.get("account_id") or "").strip()
        if not account_id:
            continue
        existing = latest.get(account_id)
        if existing is None or str(event.get("created_at") or "") >= str(existing.get("created_at") or ""):
            latest[account_id] = event
    return latest


def _extract_schwab_fill(order: dict, proposal: OptionProposal | None = None) -> dict:
    schwab_status = str(order.get("status") or "").upper()
    filled_quantity = _to_float(order.get("filledQuantity"))
    remaining_quantity = _to_float_or_none(order.get("remainingQuantity"))
    execution_fills = _execution_fills(order)
    execution_quantity = _execution_order_quantity(order, execution_fills)
    if filled_quantity <= 0 and execution_quantity > 0:
        filled_quantity = execution_quantity
    notes: list[str] = []
    average_fill_price = _to_float_or_none(order.get("averagePrice"))
    if average_fill_price is None and execution_fills:
        total_quantity = sum(float(fill["quantity"]) for fill in execution_fills)
        if total_quantity > 0:
            average_fill_price = round(
                sum(float(fill["quantity"]) * float(fill["price"]) for fill in execution_fills) / total_quantity,
                4,
            )
    net_complex_fill_price = _net_complex_fill_price(order, execution_fills, filled_quantity, proposal)
    if net_complex_fill_price is not None:
        if average_fill_price is not None and abs(average_fill_price - net_complex_fill_price) > 0.0001:
            notes.append("Schwab leg-level fills normalized to the net spread fill price.")
        average_fill_price = net_complex_fill_price
    normalized_status = _normalize_order_fill_status(schwab_status, filled_quantity, remaining_quantity)
    if average_fill_price is None and filled_quantity > 0:
        notes.append("Schwab reported filled quantity but no average fill price.")
    return {
        "status": normalized_status,
        "schwab_status": schwab_status,
        "filled_quantity": filled_quantity,
        "remaining_quantity": remaining_quantity,
        "average_fill_price": average_fill_price,
        "notes": notes,
    }


def _execution_fills(order: dict) -> list[dict]:
    fills: list[dict] = []
    activities = order.get("orderActivityCollection")
    if not isinstance(activities, list):
        return fills
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        legs = activity.get("executionLegs")
        if not isinstance(legs, list):
            continue
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            price = _to_float_or_none(leg.get("price"))
            if price is None:
                price = _to_float_or_none(leg.get("fillPrice"))
            quantity = _to_float(leg.get("quantity"))
            if price is not None and quantity > 0:
                fills.append(
                    {
                        "quantity": quantity,
                        "price": price,
                        "leg_id": _execution_leg_id(leg),
                    }
                )
    return fills


def _execution_leg_id(leg: dict) -> str | None:
    for key in ("legId", "orderLegId", "leg_id", "order_leg_id"):
        value = leg.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _execution_order_quantity(order: dict, execution_fills: list[dict]) -> float:
    if not execution_fills:
        return 0.0
    if _is_complex_net_order(order, None):
        by_leg: dict[str, float] = {}
        anonymous_quantities: list[float] = []
        for index, fill in enumerate(execution_fills):
            quantity = float(fill["quantity"])
            leg_id = fill.get("leg_id")
            if leg_id:
                by_leg[str(leg_id)] = by_leg.get(str(leg_id), 0.0) + quantity
            else:
                anonymous_quantities.append(quantity)
        if by_leg:
            return min(by_leg.values())
        if anonymous_quantities:
            return min(anonymous_quantities)
    return sum(float(fill["quantity"]) for fill in execution_fills)


def _net_complex_fill_price(
    order: dict,
    execution_fills: list[dict],
    filled_quantity: float,
    proposal: OptionProposal | None,
) -> float | None:
    if not execution_fills or not _is_complex_net_order(order, proposal):
        return None
    order_type = str(order.get("orderType") or "").upper()
    signs_by_id, signs_by_index = _order_leg_net_signs(order, order_type)
    if not signs_by_index and proposal is not None:
        signs_by_index = _proposal_leg_net_signs(proposal, order_type)
    if not signs_by_id and not signs_by_index:
        return None

    signed_notional = 0.0
    for index, fill in enumerate(execution_fills):
        sign = None
        leg_id = fill.get("leg_id")
        if leg_id is not None:
            sign = signs_by_id.get(str(leg_id))
        if sign is None and signs_by_index:
            sign = signs_by_index[index % len(signs_by_index)]
        if sign is None:
            return None
        signed_notional += sign * float(fill["quantity"]) * float(fill["price"])

    denominator = filled_quantity if filled_quantity > 0 else _execution_order_quantity(order, execution_fills)
    if denominator <= 0:
        denominator = _to_float(order.get("quantity"))
    if denominator <= 0:
        return None
    net_price = round(signed_notional / denominator, 4)
    return net_price if net_price > 0 else None


def _is_complex_net_order(order: dict, proposal: OptionProposal | None) -> bool:
    order_type = str(order.get("orderType") or "").upper()
    strategy_type = str(order.get("complexOrderStrategyType") or "").upper()
    if order_type in {"NET_DEBIT", "NET_CREDIT"} or strategy_type in {"VERTICAL", "CUSTOM"}:
        return True
    return bool(proposal is not None and proposal.structure == "debit_vertical")


def _order_leg_net_signs(order: dict, order_type: str) -> tuple[dict[str, int], list[int]]:
    signs_by_id: dict[str, int] = {}
    signs_by_index: list[int] = []
    order_legs = order.get("orderLegCollection")
    if not isinstance(order_legs, list):
        return signs_by_id, signs_by_index
    for index, leg in enumerate(order_legs):
        if not isinstance(leg, dict):
            continue
        sign = _instruction_net_sign(str(leg.get("instruction") or ""), order_type)
        if sign is None:
            continue
        signs_by_index.append(sign)
        for key in ("legId", "orderLegId", "leg_id", "order_leg_id"):
            value = leg.get(key)
            if value not in (None, ""):
                signs_by_id[str(value)] = sign
        signs_by_id.setdefault(str(index), sign)
        signs_by_id.setdefault(str(index + 1), sign)
    return signs_by_id, signs_by_index


def _proposal_leg_net_signs(proposal: OptionProposal, order_type: str) -> list[int]:
    signs: list[int] = []
    for leg in proposal.legs:
        instruction = "BUY" if leg.action == "BUY" else "SELL"
        sign = _instruction_net_sign(instruction, order_type)
        if sign is not None:
            signs.append(sign)
    return signs


def _instruction_net_sign(instruction: str, order_type: str) -> int | None:
    normalized = instruction.upper()
    is_buy = normalized.startswith("BUY")
    is_sell = normalized.startswith("SELL")
    if not (is_buy or is_sell):
        return None
    if order_type == "NET_CREDIT":
        return 1 if is_sell else -1
    return 1 if is_buy else -1


def _normalize_order_fill_status(
    schwab_status: str,
    filled_quantity: float,
    remaining_quantity: float | None,
) -> str:
    if schwab_status in {"FILLED", "EXECUTED"}:
        return "filled"
    if schwab_status in {"CANCELED", "CANCELLED", "EXPIRED"}:
        return "canceled"
    if schwab_status in {"REJECTED"}:
        return "rejected"
    if filled_quantity > 0:
        if remaining_quantity is None or remaining_quantity > 0:
            return "partial"
        return "filled"
    if schwab_status in {"QUEUED", "WORKING", "PENDING_ACTIVATION", "ACCEPTED", "AWAITING_PARENT_ORDER"}:
        return "open"
    return "unknown"


def _exit_target_previews(
    proposal: OptionProposal,
    average_fill_price: float | None,
    filled_quantity: float,
) -> list[ProposalExitTargetPreview]:
    if average_fill_price is None or filled_quantity <= 0:
        return []
    filled_contracts = max(0, int(math.floor(filled_quantity)))
    previews: list[ProposalExitTargetPreview] = []
    for target_index, target in enumerate(proposal.exit_targets):
        quantity = min(int(target.qty), filled_contracts)
        if quantity <= 0:
            continue
        target_price = round(average_fill_price * (1 + target.target_percent / 100), 2)
        if proposal.structure == "debit_vertical" and proposal.width:
            target_price = min(target_price, round(float(proposal.width), 2))
        estimated_profit = round(max(0.0, (target_price - average_fill_price) * 100 * quantity), 2)
        previews.append(
            ProposalExitTargetPreview(
                target_index=target_index,
                qty=quantity,
                target_percent=target.target_percent,
                entry_fill_price=round(average_fill_price, 4),
                target_limit_price=target_price,
                estimated_profit=estimated_profit,
                tos_exit_order_line=_tos_exit_order_line_for_proposal(proposal, quantity, target_price),
            )
        )
    return previews


def _send_proposal_exit_response(
    *,
    cfg: BridgeConfig,
    accounts: list,
    signal_id: str,
    proposal: OptionProposal,
    target_index: int,
    selected_account_ids: list[str],
    confirm_live_order: bool,
    order_note: str,
    order_status: ProposalOrderStatusResponse,
    order_client: SchwabMarketDataClient,
    order_audit: OrderAuditStore,
) -> ProposalSendResponse:
    accounts_by_id = {account.id: account for account in accounts if account.enabled}
    statuses_by_account = {status.account_id: status for status in order_status.account_statuses}
    account_results: list[ProposalAccountSendResult] = []
    if not selected_account_ids:
        return ProposalSendResponse(
            status="blocked",
            signal_id=signal_id,
            proposal_id=proposal.id,
            selected_account_ids=[],
            order_note=order_note,
            notes=["Select at least one Schwab account before sending a target exit."],
        )
    live_gate_open = (
        cfg.service.execution_mode == "live"
        and cfg.service.allow_live_orders
        and cfg.risk.trading_enabled
    )
    for account_id in selected_account_ids:
        account = accounts_by_id.get(account_id)
        if account is None:
            continue
        fill_status = statuses_by_account.get(account_id)
        target = _target_preview_for_account(fill_status, target_index)
        reasons: list[str] = []
        order_payload = None
        if proposal.structure == "debit_vertical" and not account.supports_spreads:
            reasons.append("account_not_spread_approved")
        if not account.account_hash:
            reasons.append("account_hash_missing")
        if fill_status is None:
            reasons.append("entry_order_status_missing")
        elif fill_status.status not in {"filled", "partial"} or fill_status.average_fill_price is None:
            reasons.append("entry_order_not_filled")
        if target is None:
            reasons.append("exit_target_unavailable")
        else:
            order_payload = _schwab_exit_order_payload(proposal, target)
        existing_exit_broker_order_id = None
        if order_payload is not None and account.account_hash:
            duplicate_reason, existing_exit_broker_order_id = _existing_target_exit_guard(
                order_audit=order_audit,
                order_client=order_client,
                account=account,
                signal_id=signal_id,
                proposal_id=proposal.id,
                target_index=target_index,
            )
            if duplicate_reason:
                reasons.append(duplicate_reason)
        if not live_gate_open:
            reasons.append("live_orders_blocked")
        elif not confirm_live_order:
            reasons.append("live_order_confirmation_required")
        if any(reason not in {"live_orders_blocked", "live_order_confirmation_required"} for reason in reasons):
            status = "blocked"
        elif live_gate_open and confirm_live_order and order_payload is not None:
            try:
                placement = order_client.place_order(account.account_hash, order_payload)
                result = ProposalAccountSendResult(
                    account_id=account.id,
                    account_label=account.label or account.id,
                    status="submitted",
                    reasons=["schwab_exit_order_submitted"],
                    broker_order_id=str(placement.get("broker_order_id") or "") or None,
                    order_payload=order_payload,
                    order_note=order_note,
                )
                account_results.append(result)
                _append_exit_order_audit_event(
                    order_audit,
                    signal_id=signal_id,
                    proposal=proposal,
                    target_index=target_index,
                    selected_account_ids=selected_account_ids,
                    result=result,
                    order_note=order_note,
                    fill_status=fill_status,
                    target=target,
                )
                continue
            except (SchwabApiError, RuntimeError) as exc:
                status = "blocked"
                reasons.append(f"schwab_exit_order_submit_failed:{exc}")
        else:
            status = "dry_run" if "live_orders_blocked" in reasons else "blocked"
        result = ProposalAccountSendResult(
            account_id=account.id,
            account_label=account.label or account.id,
            status=status,
            reasons=list(dict.fromkeys(reasons or ["exit_order_payload_ready"])),
            broker_order_id=existing_exit_broker_order_id,
            order_payload=order_payload if status != "blocked" else None,
            order_note=order_note,
        )
        account_results.append(result)
        _append_exit_order_audit_event(
            order_audit,
            signal_id=signal_id,
            proposal=proposal,
            target_index=target_index,
            selected_account_ids=selected_account_ids,
            result=result,
            order_note=order_note,
            fill_status=fill_status,
            target=target,
        )
    status = _aggregate_send_status(account_results)
    return ProposalSendResponse(
        status=status,
        signal_id=signal_id,
        proposal_id=proposal.id,
        selected_account_ids=selected_account_ids,
        account_results=account_results,
        order_note=order_note,
        notes=[_send_exit_response_note(status)],
    )


def _existing_target_exit_guard(
    *,
    order_audit: OrderAuditStore | None,
    order_client: SchwabMarketDataClient,
    account,
    signal_id: str,
    proposal_id: str,
    target_index: int,
) -> tuple[str | None, str | None]:
    if order_audit is None:
        return None, None
    for event in _submitted_exit_events_for_account(order_audit, signal_id, proposal_id, account.id, target_index):
        broker_order_id = str(event.get("broker_order_id") or "").strip()
        if not broker_order_id:
            continue
        try:
            order = order_client.get_order(account.account_hash, broker_order_id)
        except (SchwabApiError, RuntimeError) as exc:
            return f"target_exit_status_unverified:{broker_order_id}:{exc}", broker_order_id
        schwab_status = str(order.get("status") or "").upper()
        filled_quantity = _to_float(order.get("filledQuantity"))
        remaining_quantity = _to_float_or_none(order.get("remainingQuantity"))
        normalized_status = _normalize_order_fill_status(schwab_status, filled_quantity, remaining_quantity)
        display_status = schwab_status or normalized_status.upper()
        if filled_quantity > 0 or normalized_status in {"filled", "partial"}:
            return f"target_exit_already_filled:{broker_order_id}:{display_status}", broker_order_id
        if normalized_status == "open":
            return f"target_exit_already_active:{broker_order_id}:{display_status}", broker_order_id
        if normalized_status in {"canceled", "rejected"}:
            continue
        return f"target_exit_status_unverified:{broker_order_id}:{display_status}", broker_order_id
    return None, None


def _submitted_exit_events_for_account(
    order_audit: OrderAuditStore,
    signal_id: str,
    proposal_id: str,
    account_id: str,
    target_index: int,
) -> list[dict]:
    events: list[dict] = []
    for event in order_audit.list_events():
        if event.get("event_type") != "proposal_exit_send":
            continue
        if event.get("signal_id") != signal_id or event.get("proposal_id") != proposal_id:
            continue
        if str(event.get("account_id") or "") != str(account_id):
            continue
        try:
            event_target_index = int(event.get("target_index"))
        except (TypeError, ValueError):
            continue
        if event_target_index != int(target_index):
            continue
        if event.get("status") != "submitted" or not event.get("broker_order_id"):
            continue
        events.append(event)
    return sorted(events, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _target_preview_for_account(
    fill_status: ProposalOrderFillAccountStatus | None,
    target_index: int,
) -> ProposalExitTargetPreview | None:
    if fill_status is None:
        return None
    return next((target for target in fill_status.exit_targets if target.target_index == target_index), None)


def _send_exit_response_note(status: str) -> str:
    if status == "submitted":
        return "Schwab target exit submission was attempted for every filled selected account."
    if status == "dry_run":
        return "Target exit payloads were prepared for filled accounts. No Schwab order was submitted while live execution gates remain off."
    return "No Schwab target exit was submitted for at least one selected account; review account-level reasons."


def _schwab_exit_order_payload(proposal: OptionProposal, target: ProposalExitTargetPreview) -> dict:
    return {
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "NET_CREDIT" if proposal.structure == "debit_vertical" else "LIMIT",
        "complexOrderStrategyType": "VERTICAL" if proposal.structure == "debit_vertical" else "NONE",
        "quantity": target.qty,
        "price": f"{target.target_limit_price:.2f}",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "SELL_TO_CLOSE" if leg.action == "BUY" else "BUY_TO_CLOSE",
                "quantity": target.qty,
                "instrument": {
                    "symbol": leg.broker_symbol or _fallback_broker_option_symbol(leg),
                    "assetType": "OPTION",
                },
            }
            for leg in proposal.legs
        ],
    }


def _tos_exit_order_line_for_proposal(proposal: OptionProposal, quantity: int, limit_price: float) -> str:
    strikes = [leg.strike for leg in proposal.legs]
    structure = "VERTICAL" if proposal.structure == "debit_vertical" else "SINGLE"
    right = proposal.legs[0].right if proposal.legs else "CALL"
    strike_text = "/".join(_format_strike(strike) for strike in strikes)
    return (
        f"SELL -{quantity} {structure} {proposal.symbol.upper()} 100 "
        f"{proposal.expiry:%d %b %y} {strike_text} {right} @{limit_price:.2f} LMT GTC"
    ).upper()


def _format_strike(strike: float) -> str:
    return str(int(strike)) if float(strike).is_integer() else str(strike)


def _to_float(value) -> float:
    result = _to_float_or_none(value)
    return 0.0 if result is None else result


def _to_float_or_none(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_exit_order_audit_event(
    order_audit: OrderAuditStore | None,
    *,
    signal_id: str,
    proposal: OptionProposal,
    target_index: int,
    selected_account_ids: list[str],
    result: ProposalAccountSendResult,
    order_note: str,
    fill_status: ProposalOrderFillAccountStatus | None,
    target: ProposalExitTargetPreview | None,
) -> None:
    if order_audit is None:
        return
    event = {
        "event_type": "proposal_exit_send",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signal_id": signal_id,
        "proposal_id": proposal.id,
        "target_index": target_index,
        "symbol": proposal.symbol,
        "direction": proposal.direction,
        "structure": proposal.structure,
        "expiry": proposal.expiry.isoformat(),
        "selected_account_ids": selected_account_ids,
        "order_note": order_note,
        "account_id": result.account_id,
        "account_label": result.account_label,
        "status": result.status,
        "reasons": result.reasons,
        "broker_order_id": result.broker_order_id,
        "entry_broker_order_id": fill_status.broker_order_id if fill_status else None,
        "entry_average_fill_price": fill_status.average_fill_price if fill_status else None,
        "entry_filled_quantity": fill_status.filled_quantity if fill_status else 0,
        "target_limit_price": target.target_limit_price if target else None,
        "tos_exit_order_line": target.tos_exit_order_line if target else "",
        "order_payload": result.order_payload,
    }
    try:
        order_audit.append(event)
    except OSError:
        LOGGER.exception("Failed to append exit order audit event: signal_id=%s proposal_id=%s", signal_id, proposal.id)


def _default_order_note(record: SignalRecord, proposal: OptionProposal) -> str:
    source = _display_source_name(record.payload.source_indicator or record.payload.strategy)
    signal_time = _format_note_time(record.payload.timestamp)
    target_percentages = [target.target_percent for target in proposal.exit_targets] or record.payload.profit_target_percentages
    parts = [
        source,
        f"Signal Time {signal_time}",
        f"{proposal.symbol} {proposal.direction}",
        _profit_target_note(target_percentages),
    ]
    return " | ".join(part for part in parts if part)


def _default_exit_order_note_for_record(
    record: SignalRecord | None,
    proposal: OptionProposal,
    target_index: int,
) -> str:
    if record is None:
        return _default_exit_order_note_from_proposal(proposal, target_index)
    return _default_exit_order_note(record, proposal, target_index)


def _default_exit_order_note(record: SignalRecord, proposal: OptionProposal, target_index: int) -> str:
    base = _default_order_note(record, proposal)
    if target_index < len(proposal.exit_targets):
        target = proposal.exit_targets[target_index]
        return f"{base} | Exit target {target.target_percent:g}%"
    return f"{base} | Exit target"


def _default_exit_order_note_from_proposal(proposal: OptionProposal, target_index: int) -> str:
    parts = ["Schwab target exit", f"{proposal.symbol} {proposal.direction}"]
    if target_index < len(proposal.exit_targets):
        target = proposal.exit_targets[target_index]
        parts.append(f"Exit target {target.target_percent:g}%")
    return " | ".join(parts)


def _profit_target_note(targets: list[float]) -> str:
    if not targets:
        return ""
    formatted = "/".join(f"{target:g}%" for target in targets)
    return f"Targets {formatted}"


def _display_source_name(value: str) -> str:
    normalized = value.strip()
    compact = normalized.replace(" ", "").replace("_DoubleArrow", "").lower()
    if compact in {"ultimateaipro", "ultimateaiprodoublearrow"}:
        return "UltimateAI Pro"
    return normalized or "Unknown Source"


def _format_note_time(value: datetime) -> str:
    try:
        local = value.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        local = value.astimezone(timezone.utc)
    return local.strftime("%Y-%m-%d %I:%M:%S %p %Z")


def _append_order_audit_event(
    order_audit: OrderAuditStore | None,
    *,
    signal_id: str,
    proposal: OptionProposal,
    selected_account_ids: list[str],
    result: ProposalAccountSendResult | None,
    order_note: str,
    reasons: list[str] | None = None,
) -> None:
    if order_audit is None:
        return
    event = {
        "event_type": "proposal_send",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signal_id": signal_id,
        "proposal_id": proposal.id,
        "symbol": proposal.symbol,
        "direction": proposal.direction,
        "structure": proposal.structure,
        "expiry": proposal.expiry.isoformat(),
        "quantity": proposal.quantity,
        "tos_order_line": proposal.tos_order_line,
        "natural_limit_price": proposal.natural_limit_price,
        "natural_debit": proposal.natural_debit,
        "max_loss": proposal.max_loss,
        "send_limit_price": proposal.send_limit_price,
        "price_protection": proposal.price_protection,
        "exit_targets": [target.model_dump() for target in proposal.exit_targets],
        "selected_account_ids": selected_account_ids,
        "order_note": order_note,
        "account_id": result.account_id if result else "",
        "account_label": result.account_label if result else "",
        "status": result.status if result else "blocked",
        "reasons": result.reasons if result else list(reasons or []),
        "broker_order_id": result.broker_order_id if result else None,
        "order_payload": result.order_payload if result else None,
    }
    try:
        order_audit.append(event)
    except OSError:
        LOGGER.exception("Failed to append order audit event: signal_id=%s proposal_id=%s", signal_id, proposal.id)


def _aggregate_send_status(account_results: list[ProposalAccountSendResult]) -> str:
    if not account_results or any(result.status == "blocked" for result in account_results):
        return "blocked"
    if all(result.status == "submitted" for result in account_results):
        return "submitted"
    return "dry_run"


def _send_response_note(status: str) -> str:
    if status == "submitted":
        return "Schwab order submission was attempted for every eligible selected account."
    if status == "dry_run":
        return "Schwab order payloads were prepared for eligible accounts. No Schwab order was submitted while live execution gates remain off."
    return "No Schwab order was submitted for at least one selected account; review account-level reasons."


def _schwab_order_payload(proposal: OptionProposal, limit_price: float | None = None) -> dict:
    order_price = limit_price if limit_price is not None else (
        proposal.send_limit_price
        if proposal.send_limit_price is not None
        else proposal.debit / (proposal.quantity * 100)
    )
    return {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "NET_DEBIT" if proposal.structure == "debit_vertical" else "LIMIT",
        "complexOrderStrategyType": "VERTICAL" if proposal.structure == "debit_vertical" else "NONE",
        "quantity": proposal.quantity,
        "price": f"{order_price:.2f}",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "BUY_TO_OPEN" if leg.action == "BUY" else "SELL_TO_OPEN",
                "quantity": leg.qty,
                "instrument": {
                    "symbol": leg.broker_symbol or _fallback_broker_option_symbol(leg),
                    "assetType": "OPTION",
                },
            }
            for leg in proposal.legs
        ],
    }


def _tos_order_line_for_proposal(
    proposal: OptionProposal,
    quantity: int,
    limit_price: float,
    *,
    structure: str | None = None,
    strikes: list[float] | None = None,
    right: str | None = None,
) -> str:
    strike_values = strikes or [leg.strike for leg in proposal.legs]
    strike_text = "/".join(_format_tos_strike(strike) for strike in strike_values)
    order_structure = structure or ("VERTICAL" if proposal.structure == "debit_vertical" else "SINGLE")
    order_right = right or (proposal.legs[0].right if proposal.legs else "CALL")
    return (
        f"BUY +{quantity} {order_structure} {proposal.symbol.upper()} 100 "
        f"{proposal.expiry:%d %b %y} {strike_text} {order_right} @{limit_price:.2f} LMT"
    ).upper()


def _format_tos_strike(strike: float) -> str:
    return str(int(strike)) if float(strike).is_integer() else str(strike)


def _fallback_broker_option_symbol(leg) -> str:
    compact_strike = f"{int(round(float(leg.strike) * 1000)):08d}"
    return f"{leg.symbol.upper():<6}{leg.expiry:%y%m%d}{leg.right[0]}{compact_strike}"


app = create_app()
