from __future__ import annotations

import asyncio
import json
import math
import re
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

import os

from nt_schwab_bridge.automation import AutomationConfig, AutomationEngine, Tier
from nt_schwab_bridge.config import BridgeConfig, RiskConfig, ServiceConfig
from nt_schwab_bridge.dashboard_settings import DEFAULT_STOP_LOSS_PERCENT
from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg
from nt_schwab_bridge.gex_exits import protective_stop_premium
from nt_schwab_bridge.pnl_sync import closes_from_transactions
from nt_schwab_bridge.trade_log import TradeLogStore
from nt_schwab_bridge.schwab_adapter import (
    SchwabApiError,
    SchwabMarketDataClient,
    SchwabOAuthError,
    discover_schwab_accounts,
    schwab_market_data_status,
)

from market_scanner.config import AppSettings, load_settings
from market_scanner.dashboard import dashboard_html
from market_scanner.models import (
    AccountSendResult,
    ClosePositionRequest,
    ClosePositionResponse,
    ClosePositionResult,
    PositionsResponse,
    TrackedPosition,
    TrackedPositionLeg,
    ProposalExitTargetPreview,
    ProposalOrderFillAccountStatus,
    ProposalOrderStatusResponse,
    ScanResult,
    SendExitTargetRequest,
    SendProposalRequest,
    SendProposalResponse,
)
from market_scanner.orders import fallback_broker_option_symbol, schwab_order_payload
from market_scanner.scanner import MarketScanner, ProposalBuildSettings
from market_scanner.storage import ScannerStorage


settings_load = load_settings()
settings: AppSettings = settings_load.settings
storage = ScannerStorage(settings.storage.path)
scanner = MarketScanner(settings)
trade_log_store = TradeLogStore(settings.storage.path / "trades.jsonl")
_scheduler_task: asyncio.Task | None = None

# Realized-P&L sync lookback (days). Schwab transactions older than this are not re-scanned.
_PNL_SYNC_LOOKBACK_DAYS = 14

# Automation tiers (#7). Tier 1 manual -> Tier 2 auto-queue w/ cancel window -> Tier 3 autopilot.
# These NEVER relax the live-order triple-lock or confirm_live_order; they sit on top of it.
automation_config = AutomationConfig.from_env()
automation_engine = AutomationEngine(automation_config)
kill_switch: dict = {"engaged": False, "reason": ""}

# Positions sent live from THIS dashboard this session (keyed by underlying symbol). Only these
# show up for Close-now. Cleared on restart -- mirrors the Unified Platform's bridge-tracked model.
active_positions: dict[str, dict] = {}

ACCOUNT_ALIASES = {
    "51116118": "Raghu - SEP IRA",
    "19900410": "Grow Fly 9999",
    "38824353": "Nirupa - IRA",
    "64962736": "Final Frontier",
    "26144145": "Wolf Group",
    "15419231": "Nirupa - Individual",
    "85839327": "Grow Fly",
    "93484309": "Raghu - IRA",
    "22572756": "Raghu General",
    "62058846": "Raghu Nirupa Joint",
    "32552523": "Raghu - Roth",
    "47169783": "NIFTY LLC",
    "66502618": "Individual",
}


def _bridge_config() -> BridgeConfig:
    return BridgeConfig(
        service=ServiceConfig(
            execution_mode=settings.service.execution_mode,
            allow_live_orders=settings.service.allow_live_orders,
        ),
        risk=RiskConfig(trading_enabled=settings.service.trading_enabled),
        options=settings.planner_config(),
        schwab=settings.schwab,
    )


def _require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = settings.service.api_key.strip()
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key.")


async def _scheduler_loop() -> None:
    await asyncio.sleep(3)
    while True:
        try:
            result = await asyncio.to_thread(scanner.scan, include_options=False)
            _rank_candidates(result)
            storage.save_scan(result)
        except Exception:
            pass
        await asyncio.sleep(settings.scanner.interval_minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    try:
        yield
    finally:
        if _scheduler_task is not None:
            _scheduler_task.cancel()


app = FastAPI(title="Schwab Market Scanner", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    latest = storage.load_latest_scan()
    return {
        "status": "ok",
        "service": "schwab-market-scanner",
        "config_source": settings_load.source,
        "config": settings.public_status(),
        "latest_scan_id": latest.scan_id if latest else None,
        "latest_scan_at": latest.scanned_at if latest else None,
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    # Pass the configured API key so the dashboard authenticates protected POSTs when one is set.
    return dashboard_html(api_key=settings.service.api_key)


@app.get("/schwab/status")
async def schwab_status() -> dict:
    return schwab_market_data_status(_bridge_config()).model_dump(mode="json")


def _account_alias(account_id: str) -> str:
    return ACCOUNT_ALIASES.get(str(account_id), str(account_id))


def _pnl_summary_with_aliases() -> dict:
    summary = trade_log_store.summary()
    for row in summary.get("pnl_by_account", []) or []:
        row["account_label"] = _account_alias(row.get("account_id", ""))
    return summary


def _sync_schwab_pnl() -> dict:
    """Pull recent Schwab transactions for every linked account and record realized P&L for
    fully-closed option positions (deduped by option_symbol+order_ids so vertical legs do not
    collide). Never raises -- one bad account is reported in 'errors' and the rest continue."""
    accounts, _notes = discover_schwab_accounts(_bridge_config())
    eligible = [a for a in accounts if str(getattr(a, "account_hash", "") or "").strip()]
    client = SchwabMarketDataClient(settings.schwab)
    now = datetime.now(timezone.utc)
    lookback_days = int(os.environ.get("NT_PNL_SYNC_LOOKBACK_DAYS", str(_PNL_SYNC_LOOKBACK_DAYS)))
    start = now - timedelta(days=lookback_days)
    new_closes = 0
    realized_added = 0.0
    errors: list[str] = []
    for account in eligible:
        try:
            transactions = client.get_transactions(account.account_hash, start, now)
        except Exception as exc:  # noqa: BLE001 -- one bad account must not stop the sync
            errors.append(f"{getattr(account, 'id', '?')}: {exc}")
            continue
        for close in closes_from_transactions(transactions):
            if trade_log_store.was_recorded(close.dedup_key):
                continue
            recorded = trade_log_store.record_close(
                symbol=close.underlying,
                indicator="schwab_sync",
                account_id=str(getattr(account, "id", "")),
                entry_price=close.entry_price,
                exit_price=close.exit_price,
                contracts=max(1, close.contracts),
                closed_at=_parse_audit_datetime(close.closed_at),
                realized_pnl=close.realized_pnl,
                dedup_key=close.dedup_key,
            )
            if recorded is not None:
                new_closes += 1
                realized_added = round(realized_added + close.realized_pnl, 2)
    return {
        "new_closes": new_closes,
        "realized_added": realized_added,
        "accounts_synced": len(eligible),
        "errors": errors,
        "summary": _pnl_summary_with_aliases(),
    }


@app.get("/pnl/summary")
async def pnl_summary() -> dict:
    """Realized-P&L summary: combined headline + per-account rows (with aliases)."""
    return _pnl_summary_with_aliases()


@app.post("/pnl/sync")
async def pnl_sync(_: None = Depends(_require_api_key)) -> dict:
    """Sync realized P&L from Schwab transactions (14-day lookback, deduped) and return the summary."""
    return await asyncio.to_thread(_sync_schwab_pnl)


_TIER_LABELS = {
    "off": "Off (pure manual)",
    "1": "Tier 1 - Smart Assist (manual send)",
    "2": "Tier 2 - Auto-Send w/ 10s cancel",
    "3": "Tier 3 - Full Autopilot",
}


def _automation_status_payload() -> dict:
    cfg = automation_config
    return {
        "tier": cfg.tier.value,
        "tier_label": _TIER_LABELS.get(cfg.tier.value, cfg.tier.value),
        "smart_assist_min_score": cfg.smart_assist_min_score,
        "manual_review_min_score": cfg.manual_review_min_score,
        "auto_queue_min_score": cfg.auto_queue_min_score,
        "cancel_window_seconds": cfg.cancel_window_seconds,
        "per_account_auto": dict(cfg.per_account_auto),
        "kill_switch": dict(kill_switch),
        # The triple-lock is always the final gate regardless of tier.
        "live_gate_open": settings.service.live_gate_open,
    }


@app.get("/automation/status")
async def automation_status() -> dict:
    return _automation_status_payload()


@app.post("/automation/tier")
async def automation_set_tier(payload: dict = Body(...), _: None = Depends(_require_api_key)) -> dict:
    """Switch tier. Tier 2/3 require explicit confirm=true. Risk gates still apply at every tier."""
    requested = Tier.parse(str(payload.get("tier", "1")))
    if requested in (Tier.TIER2, Tier.TIER3) and not bool(payload.get("confirm")):
        raise HTTPException(status_code=409, detail=f"Switching to {requested.value} requires confirm=true.")
    automation_config.tier = requested
    return _automation_status_payload()


@app.post("/automation/account-toggle")
async def automation_account_toggle(payload: dict = Body(...), _: None = Depends(_require_api_key)) -> dict:
    account_id = str(payload.get("account_id", "")).strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id is required.")
    automation_config.per_account_auto[account_id] = bool(payload.get("enabled"))
    return _automation_status_payload()


@app.post("/automation/kill")
async def automation_kill(payload: dict = Body(default={})) -> dict:
    """Engage the kill switch and drop to Tier 1 (manual) immediately."""
    kill_switch["engaged"] = True
    kill_switch["reason"] = str((payload or {}).get("reason", "manual"))
    automation_config.tier = Tier.TIER1
    return _automation_status_payload()


@app.post("/automation/kill/release")
async def automation_kill_release(_: None = Depends(_require_api_key)) -> dict:
    kill_switch["engaged"] = False
    kill_switch["reason"] = ""
    return _automation_status_payload()


@app.get("/automation/kill")
async def automation_kill_mobile(key: str = Query(default="")) -> dict:
    """Mobile-accessible kill via GET. Requires AUTOMATION_KILL_KEY to match."""
    expected = os.environ.get("AUTOMATION_KILL_KEY", "").strip()
    if not expected or key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing kill key.")
    kill_switch["engaged"] = True
    kill_switch["reason"] = "mobile"
    automation_config.tier = Tier.TIER1
    return _automation_status_payload()


# ---- Open positions + Close-now (#9 / the SMCI gap) --------------------------------------
# DASHBOARD-TRACKED (per Raghu 2026-06-22): only positions THIS dashboard sent live this session
# show up for Close-now -- mirrors the Unified Platform's "bridge-tracked, cleared on restart".
# The authoritative Schwab pull listed every unrelated holding, which was noise. Tradeoff: a
# position placed outside this dashboard, or before a restart, won't appear here.

def _register_active_position(proposal: OptionProposal, account_ids: list[str], accounts_by_id: dict, broker_order_ids: dict) -> None:
    """Record a live-sent position so it can be shown + closed from the dashboard this session."""
    if not account_ids:
        return
    legs = [
        {
            "action": leg.action,
            "qty": leg.qty,
            "broker_symbol": leg.broker_symbol or fallback_broker_option_symbol(leg),
            "right": leg.right,
            "strike": leg.strike,
        }
        for leg in proposal.legs
    ]
    active_positions[proposal.symbol.upper()] = {
        "symbol": proposal.symbol.upper(),
        "direction": proposal.direction,
        "structure": proposal.structure,
        "source": "scanner",
        "legs": legs,
        "account_ids": list(account_ids),
        "account_hashes": {aid: getattr(accounts_by_id.get(aid), "account_hash", "") for aid in account_ids},
        "broker_order_ids": dict(broker_order_ids),
        "sent_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _market_close_legs(legs: list[dict]) -> list[dict]:
    # Invert the opening action: long (BUY) -> SELL_TO_CLOSE, short (SELL) -> BUY_TO_CLOSE.
    return [
        {
            "instruction": "SELL_TO_CLOSE" if leg.get("action") == "BUY" else "BUY_TO_CLOSE",
            "quantity": leg.get("qty", 1),
            "instrument": {"symbol": leg.get("broker_symbol", ""), "assetType": "OPTION"},
        }
        for leg in legs
        if leg.get("broker_symbol")
    ]


def _pos_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _tracked_positions_response(client: SchwabMarketDataClient | None = None) -> PositionsResponse:
    """One row per (account, symbol) tracked this session. When a client is given, enrich each
    row with live unrealized P&L from Schwab (matched by the tracked option symbol). get_positions
    is cached per account_hash so we make at most one call per distinct account."""
    cache: dict[str, list] = {}

    def account_positions(account_hash: str) -> list:
        if account_hash not in cache:
            try:
                cache[account_hash] = client.get_positions(account_hash) if (client and account_hash) else []
            except Exception:  # noqa: BLE001 -- enrichment is best-effort; show the row without P&L
                cache[account_hash] = []
        return cache[account_hash]

    rows: list[TrackedPosition] = []
    for p in active_positions.values():
        leg_syms = {str(leg.get("broker_symbol", "")).replace(" ", "") for leg in p.get("legs", [])}
        primary = p["legs"][0] if p.get("legs") else {}
        for aid in p.get("account_ids", []):
            account_hash = str(p.get("account_hashes", {}).get(aid, "") or "")
            unrealized = None
            market_value = None
            if client and account_hash:
                total_upnl = 0.0
                total_mv = 0.0
                matched = False
                for raw in account_positions(account_hash):
                    instrument = raw.get("instrument") if isinstance(raw.get("instrument"), dict) else {}
                    sym = str((instrument or {}).get("symbol", "")).replace(" ", "")
                    if sym in leg_syms:
                        matched = True
                        total_upnl += _pos_float(raw.get("longOpenProfitLoss")) + _pos_float(raw.get("shortOpenProfitLoss"))
                        total_mv += _pos_float(raw.get("marketValue"))
                if matched:
                    unrealized = round(total_upnl, 2)
                    market_value = round(total_mv, 2)
            rows.append(
                TrackedPosition(
                    symbol=p["symbol"],
                    account_id=aid,
                    account_label=_account_alias(aid),
                    direction=p.get("direction", ""),
                    structure=p.get("structure", "single"),
                    source=p.get("source", "scanner"),
                    broker_symbol=str(primary.get("broker_symbol", "") or ""),
                    qty=int(primary.get("qty", 0) or 0),
                    unrealized_pnl=unrealized,
                    market_value=market_value,
                    sent_at=p.get("sent_at", ""),
                )
            )
    return PositionsResponse(
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        positions=rows,
        note="Dashboard-tracked live sends this session; cleared on restart.",
    )


def _open_order_ids_for_symbol(account_id: str, broker_symbol: str) -> list[str]:
    """Best-effort: resting Schwab order ids this scanner submitted for the given option
    symbol on the given account (from the order audit). Used to cancel the resting OCO/exit
    before a MARKET close so the position is not double-closed."""
    order_ids: list[str] = []
    target = broker_symbol.replace(" ", "")
    for event in storage.list_order_events():
        if str(event.get("account_id") or "") != str(account_id):
            continue
        if str(event.get("status") or "") != "submitted":
            continue
        broker_order_id = str(event.get("broker_order_id") or "").strip()
        if not broker_order_id:
            continue
        payload = event.get("order_payload")
        if not isinstance(payload, dict):
            continue
        if target in json.dumps(payload).replace(" ", ""):
            order_ids.append(broker_order_id)
    return list(dict.fromkeys(order_ids))


def _close_position_response(
    *,
    symbol: str,
    request: ClosePositionRequest,
    order_client: SchwabMarketDataClient,
) -> ClosePositionResponse:
    """Close a DASHBOARD-TRACKED position: cancel resting orders + MARKET close, per account."""
    pos = active_positions.get(symbol.upper())
    if pos is None:
        return ClosePositionResponse(
            status="blocked",
            symbol=symbol,
            notes=["No dashboard-tracked position for this symbol — only positions sent from this dashboard this session can be closed here."],
        )
    live_gate_open = settings.service.live_gate_open
    market_legs = _market_close_legs(pos["legs"])
    market_payload = {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "MARKET",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": market_legs,
    }
    broker_symbol = pos["legs"][0]["broker_symbol"] if pos.get("legs") else ""
    selected = request.selected_account_ids or pos["account_ids"]
    results: list[ClosePositionResult] = []
    for account_id in pos["account_ids"]:
        if account_id not in selected:
            continue
        account_hash = str(pos["account_hashes"].get(account_id, "") or "").strip()
        label = _account_alias(account_id)
        reasons: list[str] = []
        if not account_hash:
            reasons.append("account_hash_missing")
        if not live_gate_open:
            reasons.append("live_orders_blocked")
        elif not request.confirm_live_order:
            reasons.append("live_order_confirmation_required")
        hard_block = "account_hash_missing" in reasons or not market_legs

        if hard_block or not (live_gate_open and request.confirm_live_order):
            results.append(
                ClosePositionResult(
                    account_id=account_id,
                    account_label=label,
                    status="dry_run" if (not hard_block and "live_orders_blocked" in reasons) else "blocked",
                    reasons=list(dict.fromkeys(reasons or ["close_payload_ready"])),
                    order_payload=market_payload,
                )
            )
            continue

        canceled: list[str] = []
        for order_id in _open_order_ids_for_symbol(account_id, broker_symbol):
            try:
                order_client.cancel_order(account_hash, order_id)
                canceled.append(order_id)
            except (SchwabApiError, SchwabOAuthError):
                pass  # best-effort; the MARKET close still flattens the position
        try:
            placed = order_client.place_order(account_hash, market_payload)
            results.append(
                ClosePositionResult(
                    account_id=account_id,
                    account_label=label,
                    status="submitted",
                    reasons=["market_close_submitted"],
                    broker_order_id=str(placed.get("broker_order_id") or "") or None,
                    canceled_order_ids=canceled,
                    order_payload=market_payload,
                )
            )
        except (SchwabApiError, SchwabOAuthError) as exc:
            results.append(
                ClosePositionResult(
                    account_id=account_id,
                    account_label=label,
                    status="blocked",
                    reasons=[f"market_close_failed:{str(exc)[:200]}"],
                    canceled_order_ids=canceled,
                    order_payload=market_payload,
                )
            )

    status = _aggregate_status(results) if results else "blocked"
    notes: list[str] = []
    # Remove only the accounts that actually closed; drop the symbol entirely when none remain.
    submitted_accounts = {r.account_id for r in results if r.status == "submitted"}
    if submitted_accounts:
        pos["account_ids"] = [a for a in pos["account_ids"] if a not in submitted_accounts]
        pos["account_hashes"] = {k: v for k, v in pos["account_hashes"].items() if k in pos["account_ids"]}
        if not pos["account_ids"]:
            active_positions.pop(symbol.upper(), None)
            notes.append("Position fully closed; removed from the tracker.")
        else:
            notes.append(f"Closed {len(submitted_accounts)} account(s); {len(pos['account_ids'])} still open.")
    return ClosePositionResponse(status=status, symbol=symbol, account_results=results, notes=notes)


@app.get("/positions", response_model=PositionsResponse)
async def positions() -> PositionsResponse:
    """Dashboard-tracked open positions (live sends this session; cleared on restart),
    enriched with live unrealized P&L from Schwab. No tracked positions -> no Schwab calls."""
    client = SchwabMarketDataClient(settings.schwab) if active_positions else None
    return await asyncio.to_thread(_tracked_positions_response, client)


@app.post("/positions/{symbol}/close", response_model=ClosePositionResponse)
async def close_position(
    symbol: str,
    request: ClosePositionRequest,
    _: None = Depends(_require_api_key),
) -> ClosePositionResponse:
    """Close a dashboard-tracked position now: cancel resting orders + MARKET close. Triple-lock + confirm gated."""
    client = SchwabMarketDataClient(settings.schwab)
    response = await asyncio.to_thread(
        lambda: _close_position_response(symbol=symbol, request=request, order_client=client)
    )
    storage.append_order_event(
        {
            "event_type": "position_close_batch",
            "symbol": symbol,
            "status": response.status,
            "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "account_results": [r.model_dump(mode="json") for r in response.account_results],
        }
    )
    return response


@app.get("/accounts")
async def accounts(_: None = Depends(_require_api_key)) -> dict:
    discovered, notes = discover_schwab_accounts(_bridge_config())
    balances, balance_notes = _account_balance_summaries(discovered)
    return {
        "accounts": [
            {
                "id": account.id,
                "label": _account_display_label(account),
                "account_number": account.account_number,
                "source": account.source,
                "account_type": account.account_type,
                "supports_spreads": account.supports_spreads,
                "enabled": account.enabled,
                "default_selected": account.default_selected,
                "order_configured": bool(account.account_hash),
                "balance": balances.get(account.id, {}),
            }
            for account in discovered
        ],
        "notes": [*notes, *balance_notes],
    }


@app.post("/scan/run", response_model=ScanResult)
async def run_scan(
    _: None = Depends(_require_api_key),
    include_options: bool = True,
    expiry_label: str | None = None,
    allow_itm: bool | None = None,
    max_loss: float | None = Query(default=None, ge=0),
    entry_offset_cents: float | None = Query(default=None, ge=0),
    target_percentages: str | None = None,
) -> ScanResult:
    result = await asyncio.to_thread(
        scanner.scan,
        include_options=include_options,
        build_settings=_proposal_build_settings(
            expiry_label=expiry_label,
            allow_itm=allow_itm,
            max_loss=max_loss,
            entry_offset_cents=entry_offset_cents,
            target_percentages=target_percentages,
        )
        if include_options
        else None,
    )
    _rank_candidates(result)
    storage.save_scan(result)
    return result


@app.post("/scan/selected/{symbol}", response_model=ScanResult)
async def build_selected_scan_proposals(
    symbol: str,
    _: None = Depends(_require_api_key),
    expiry_label: str | None = None,
    allow_itm: bool | None = None,
    max_loss: float | None = Query(default=None, ge=0),
    entry_offset_cents: float | None = Query(default=None, ge=0),
    target_percentages: str | None = None,
) -> ScanResult:
    normalized = symbol.upper().replace("$", "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Symbol is required.")
    result = storage.load_latest_scan()
    if result is None:
        result = await asyncio.to_thread(scanner.scan, include_options=False)
        _rank_candidates(result)
    build_settings = _proposal_build_settings(
        expiry_label=expiry_label,
        allow_itm=allow_itm,
        max_loss=max_loss,
        entry_offset_cents=entry_offset_cents,
        target_percentages=target_percentages,
    )
    try:
        result = await asyncio.to_thread(
            scanner.build_selected_candidate_proposals,
            result,
            normalized,
            None,
            build_settings,
        )
    except ValueError:
        result = await asyncio.to_thread(scanner.scan, include_options=False)
        _rank_candidates(result)
        try:
            result = await asyncio.to_thread(
                scanner.build_selected_candidate_proposals,
                result,
                normalized,
                None,
                build_settings,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    _rank_candidates(result)
    storage.save_scan(result)
    return result


@app.post("/scan/replay", response_model=ScanResult)
async def replay_scan(
    _: None = Depends(_require_api_key),
    as_of: Annotated[
        str | None,
        Query(description="ISO datetime, or YYYY-MM-DD to replay that date at 09:29 New York time."),
    ] = None,
    save: bool = True,
    include_options: bool = False,
    simulate_options: bool = False,
) -> ScanResult:
    replay_as_of = _parse_replay_as_of(as_of)
    if simulate_options:
        option_note = (
            "Historical replay generated SIM_ONLY proposals from Friday underlying prices and current Schwab "
            "option-chain contract data."
        )
    elif include_options:
        option_note = "Historical replay used current Schwab option-chain data because include_options=true."
    else:
        option_note = (
            "Historical replay skipped option proposals because Schwab option-chain data is current, not a "
            "historical snapshot."
        )
    result = await asyncio.to_thread(
        scanner.scan,
        replay_as_of,
        use_live_quotes=False,
        include_options=include_options,
        simulate_options=simulate_options,
        notes=[
            f"Historical replay as of {replay_as_of.isoformat()}; live quotes ignored.",
            option_note,
        ],
    )
    _rank_candidates(result)
    if save:
        storage.save_scan(result)
    return result


@app.get("/scan/latest", response_model=ScanResult | dict)
async def latest_scan() -> ScanResult | dict:
    result = storage.load_latest_scan()
    if result is None:
        return {"status": "not_found", "message": "No scan has been run yet."}
    return result


@app.post("/proposals/{proposal_id}/send", response_model=SendProposalResponse)
async def send_proposal(
    proposal_id: str,
    request: SendProposalRequest,
    _: None = Depends(_require_api_key),
) -> SendProposalResponse:
    proposal = storage.find_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found in latest scan.")
    if _is_simulated_proposal(proposal):
        response = SendProposalResponse(
            status="blocked",
            proposal_id=proposal_id,
            selected_account_ids=list(dict.fromkeys(request.selected_account_ids)),
            notes=[
                "SIM_ONLY historical replay proposals are blocked from Schwab order submission.",
                "Run a current live scan during market/options hours for orderable proposal payloads.",
            ],
        )
        storage.append_order_event(_send_response_audit_event(response, proposal))
        return response

    selected_ids = list(dict.fromkeys(request.selected_account_ids))
    accounts, account_notes = discover_schwab_accounts(_bridge_config())
    accounts_by_id = {account.id: account for account in accounts if account.enabled}
    if not selected_ids:
        response = SendProposalResponse(
            status="blocked",
            proposal_id=proposal_id,
            selected_account_ids=[],
            notes=["Select at least one Schwab account before sending.", *account_notes],
        )
        storage.append_order_event(_send_response_audit_event(response, proposal))
        return response

    proposal_to_send = proposal
    if request.quantity is not None and request.quantity != proposal.quantity:
        proposal_to_send = proposal.model_copy(
            update={
                "quantity": request.quantity,
                "legs": [leg.model_copy(update={"qty": request.quantity}) for leg in proposal.legs],
            }
        )
    order_payload = schwab_order_payload(proposal_to_send, limit_price=request.limit_price)
    live_gate_open = settings.service.live_gate_open
    client = SchwabMarketDataClient(settings.schwab)
    results: list[AccountSendResult] = []

    for account_id in selected_ids:
        account = accounts_by_id.get(account_id)
        if account is None:
            results.append(
                AccountSendResult(
                    account_id=account_id,
                    account_label=account_id,
                    status="blocked",
                    reasons=["account_not_found_or_disabled"],
                )
            )
            continue
        reasons: list[str] = []
        if proposal.structure == "debit_vertical" and not account.supports_spreads:
            reasons.append("account_not_spread_approved")
        if not account.account_hash:
            reasons.append("account_hash_missing")
        if not live_gate_open:
            reasons.append("live_orders_blocked")
        elif not request.confirm_live_order:
            reasons.append("live_order_confirmation_required")

        if any(reason not in {"live_orders_blocked", "live_order_confirmation_required"} for reason in reasons):
            results.append(
                AccountSendResult(
                    account_id=account.id,
                    account_label=_account_display_label(account),
                    status="blocked",
                    reasons=reasons,
                )
            )
            continue
        if live_gate_open and request.confirm_live_order:
            try:
                placed = client.place_order(account.account_hash, order_payload)
                results.append(
                    AccountSendResult(
                        account_id=account.id,
                        account_label=_account_display_label(account),
                        status="submitted",
                        reasons=["schwab_order_submitted"],
                        broker_order_id=str(placed.get("broker_order_id") or "") or None,
                        order_payload=order_payload,
                    )
                )
            except SchwabApiError as exc:
                results.append(
                    AccountSendResult(
                        account_id=account.id,
                        account_label=_account_display_label(account),
                        status="blocked",
                        reasons=[f"schwab_order_submit_failed:{str(exc)[:200]}"],
                        order_payload=order_payload,
                    )
                )
        else:
            results.append(
                AccountSendResult(
                    account_id=account.id,
                    account_label=_account_display_label(account),
                    status="dry_run" if "live_orders_blocked" in reasons else "blocked",
                    reasons=reasons or ["order_payload_ready"],
                    order_payload=order_payload,
                )
            )

    status = _aggregate_status(results)
    # Track live-submitted positions so they (and only they) appear for dashboard Close-now.
    submitted = {r.account_id: r.broker_order_id for r in results if r.status == "submitted"}
    if submitted:
        _register_active_position(proposal_to_send, list(submitted.keys()), accounts_by_id, submitted)
    response = SendProposalResponse(
        status=status,
        proposal_id=proposal_id,
        selected_account_ids=selected_ids,
        account_results=results,
        notes=[
            _send_note(status),
            f"Recorded at {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}",
        ],
    )
    storage.append_order_event(_send_response_audit_event(response, proposal_to_send))
    return response


@app.get("/proposals/{proposal_id}/orders/status", response_model=ProposalOrderStatusResponse)
async def proposal_order_status(
    proposal_id: str,
    target_percentages: Annotated[
        str | None,
        Query(description="Comma-separated exit target percentages, for example 25,50,60."),
    ] = None,
    stop_loss_percent: Annotated[
        float,
        Query(ge=0, le=99, description="Protective OCO stop, percent below entry fill (single-leg). 0 disables the stop."),
    ] = float(DEFAULT_STOP_LOSS_PERCENT),
) -> ProposalOrderStatusResponse:
    proposal = storage.find_proposal(proposal_id)
    if proposal is None:
        proposal = _proposal_from_order_audit(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found in latest scan or order audit.")
    accounts, _account_notes = discover_schwab_accounts(_bridge_config())
    client = SchwabMarketDataClient(settings.schwab)
    return _proposal_order_status_response(
        proposal=proposal,
        accounts=accounts,
        order_client=client,
        target_percentages=_parse_target_percentages(target_percentages),
        stop_loss_percent=stop_loss_percent,
    )


@app.post("/proposals/{proposal_id}/targets/{target_index}/send", response_model=SendProposalResponse)
async def send_exit_target(
    proposal_id: str,
    target_index: int,
    request: SendExitTargetRequest,
    _: None = Depends(_require_api_key),
    target_percentages: Annotated[
        str | None,
        Query(description="Comma-separated exit target percentages, for example 20,50,60."),
    ] = None,
    stop_loss_percent: Annotated[
        float,
        Query(ge=0, le=99, description="Protective OCO stop, percent below entry fill (single-leg). 0 disables the stop."),
    ] = float(DEFAULT_STOP_LOSS_PERCENT),
) -> SendProposalResponse:
    proposal = storage.find_proposal(proposal_id)
    if proposal is None:
        proposal = _proposal_from_order_audit(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found in latest scan or order audit.")
    accounts, account_notes = discover_schwab_accounts(_bridge_config())
    client = SchwabMarketDataClient(settings.schwab)
    order_status = _proposal_order_status_response(
        proposal=proposal,
        accounts=accounts,
        order_client=client,
        target_percentages=_parse_target_percentages(target_percentages),
        stop_loss_percent=stop_loss_percent,
    )
    response = _send_exit_target_response(
        proposal=proposal,
        target_index=target_index,
        request=request,
        accounts=accounts,
        account_notes=account_notes,
        order_status=order_status,
        order_client=client,
    )
    storage.append_order_event(_exit_response_audit_event(response, proposal, target_index, order_status))
    return response


def _rank_candidates(result: ScanResult) -> None:
    for index, candidate in enumerate(result.candidates, start=1):
        candidate.rank = index
    top_ids = {candidate.symbol for candidate in result.candidates[: settings.scanner.top_n]}
    result.top_candidates = [candidate for candidate in result.candidates if candidate.symbol in top_ids]


def _account_display_label(account) -> str:
    for value in (getattr(account, "account_number", ""), getattr(account, "label", ""), getattr(account, "id", "")):
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if digits in ACCOUNT_ALIASES:
            return ACCOUNT_ALIASES[digits]
        matches = [
            alias
            for account_number, alias in ACCOUNT_ALIASES.items()
            if len(digits) >= 4 and account_number.endswith(digits)
        ]
        if len(matches) == 1:
            return matches[0]
    return getattr(account, "label", "") or getattr(account, "account_number", "") or getattr(account, "id", "")


def _account_balance_summaries(accounts: list) -> tuple[dict[str, dict], list[str]]:
    eligible_accounts = [
        account
        for account in accounts
        if getattr(account, "enabled", False) and str(getattr(account, "account_hash", "") or "").strip()
    ]
    if not eligible_accounts:
        return {}, []
    if not settings.schwab.market_data_enabled:
        return {}, []
    if not (settings.schwab.token_store_path or settings.schwab.access_token or settings.schwab.refresh_token):
        return {}, ["Schwab account balances require a configured Schwab token source."]

    client = SchwabMarketDataClient(settings.schwab)
    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    balances: dict[str, dict] = {}
    notes: list[str] = []
    for account in eligible_accounts:
        try:
            summary = client.get_account_balance_summary(account.account_hash)
            balances[account.id] = {
                "available_to_trade": summary.get("available_to_trade"),
                "buying_power": summary.get("buying_power"),
                "cash_balance": summary.get("cash_balance"),
                "source": str(summary.get("source", "") or ""),
                "updated_at": updated_at,
            }
        except (SchwabApiError, SchwabOAuthError) as exc:
            balances[account.id] = {"updated_at": updated_at, "error": str(exc)}
            notes.append(f"Schwab balance lookup failed for {_account_display_label(account)}: {exc}")
    return balances, notes


def _send_response_audit_event(response: SendProposalResponse, proposal: OptionProposal) -> dict:
    payload = response.model_dump(mode="json")
    payload["event_type"] = "proposal_send_batch"
    payload["proposal"] = proposal.model_dump(mode="json")
    return payload


def _proposal_from_order_audit(proposal_id: str) -> OptionProposal | None:
    latest_event: dict | None = None
    for event in storage.list_order_events():
        if event.get("proposal_id") != proposal_id:
            continue
        proposal_payload = event.get("proposal")
        if not isinstance(proposal_payload, dict):
            continue
        if latest_event is None or str(event.get("recorded_at") or "") >= str(latest_event.get("recorded_at") or ""):
            latest_event = event
    if latest_event is not None:
        try:
            return OptionProposal.model_validate(latest_event["proposal"])
        except ValueError:
            pass

    fallback_event: dict | None = None
    fallback_payload: dict | None = None
    for event in storage.list_order_events():
        if event.get("proposal_id") != proposal_id:
            continue
        for result in _account_order_events(event):
            order_payload = result.get("order_payload")
            if not isinstance(order_payload, dict):
                continue
            if fallback_event is None or str(result.get("created_at") or "") >= str(fallback_event.get("created_at") or ""):
                fallback_event = result
                fallback_payload = order_payload
    if fallback_payload is None:
        return None
    return _proposal_from_order_payload(
        proposal_id=proposal_id,
        order_payload=fallback_payload,
        created_at=str(fallback_event.get("created_at") or "") if fallback_event else "",
    )


def _proposal_from_order_payload(
    *,
    proposal_id: str,
    order_payload: dict,
    created_at: str,
) -> OptionProposal | None:
    raw_legs = order_payload.get("orderLegCollection")
    if not isinstance(raw_legs, list):
        return None
    order_price = _to_float(order_payload.get("price"))
    order_quantity = max(1, int(_to_float(order_payload.get("quantity")) or 1))
    legs: list[OptionProposalLeg] = []
    for raw_leg in raw_legs:
        if not isinstance(raw_leg, dict):
            continue
        instrument = raw_leg.get("instrument")
        if not isinstance(instrument, dict):
            continue
        parsed = _parse_broker_option_symbol(str(instrument.get("symbol") or ""))
        if parsed is None:
            continue
        symbol, expiry, right, strike = parsed
        instruction = str(raw_leg.get("instruction") or "").upper()
        action = "SELL" if instruction.startswith("SELL") else "BUY"
        leg_quantity = max(1, int(_to_float(raw_leg.get("quantity")) or order_quantity))
        legs.append(
            OptionProposalLeg(
                action=action,
                qty=leg_quantity,
                symbol=symbol,
                broker_symbol=str(instrument.get("symbol") or ""),
                expiry=expiry,
                strike=strike,
                right=right,
                price=order_price,
            )
        )
    if not legs:
        return None
    complex_type = str(order_payload.get("complexOrderStrategyType") or "").upper()
    order_type = str(order_payload.get("orderType") or "").upper()
    structure = "debit_vertical" if len(legs) > 1 or complex_type == "VERTICAL" or order_type.startswith("NET") else "single"
    strikes = [float(leg.strike) for leg in legs]
    width = abs(strikes[0] - strikes[1]) if len(strikes) >= 2 else None
    debit = round(order_price * order_quantity * 100, 2)
    right = legs[0].right
    created = _parse_audit_datetime(created_at) or datetime.now(timezone.utc)
    direction = "short" if right == "PUT" else "long"
    return OptionProposal(
        id=proposal_id,
        signal_id=f"audit_{proposal_id}",
        symbol=legs[0].symbol,
        direction=direction,
        structure=structure,
        created_at=created,
        expiry=legs[0].expiry,
        quantity=order_quantity,
        legs=legs,
        debit=debit,
        max_loss=debit,
        natural_limit_price=order_price,
        natural_debit=debit,
        send_limit_price=order_price,
        width=width,
        tos_order_line="",
        reasons=["restored_from_order_audit"],
        notes=["Restored from submitted Schwab order audit; use Get Order Info to refresh actual fill."],
        dry_run=False,
    )


def _parse_broker_option_symbol(value: str) -> tuple[str, date_type, str, float] | None:
    match = re.match(r"^(.{1,6})(\d{6})([CP])(\d{8})$", value.strip())
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


def _parse_audit_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _proposal_order_status_response(
    *,
    proposal: OptionProposal,
    accounts: list,
    order_client: SchwabMarketDataClient,
    target_percentages: list[float],
    stop_loss_percent: float = 0.0,
) -> ProposalOrderStatusResponse:
    submitted_by_account = _submitted_entry_events_by_account(proposal.id)
    accounts_by_id = {account.id: account for account in accounts if getattr(account, "enabled", False)}
    statuses: list[ProposalOrderFillAccountStatus] = []

    for account_id, event in submitted_by_account.items():
        account = accounts_by_id.get(account_id)
        account_label = (
            _account_display_label(account)
            if account is not None
            else str(event.get("account_label") or event.get("account_id") or account_id)
        )
        broker_order_id = str(event.get("broker_order_id") or "").strip()
        order_payload = event.get("order_payload") if isinstance(event.get("order_payload"), dict) else None
        if not broker_order_id:
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account_id,
                    account_label=account_label,
                    status="unknown",
                    order_payload=order_payload,
                    notes=["Submitted entry audit exists, but no Schwab order id was recorded."],
                )
            )
            continue
        if account is None:
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account_id,
                    account_label=account_label,
                    broker_order_id=broker_order_id,
                    status="error",
                    order_payload=order_payload,
                    notes=["Submitted account is not currently enabled or discoverable; cannot query Schwab order status."],
                )
            )
            continue
        if not getattr(account, "account_hash", ""):
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account.id,
                    account_label=account_label,
                    broker_order_id=broker_order_id,
                    status="error",
                    order_payload=order_payload,
                    notes=["Account hash is missing; cannot query Schwab order status."],
                )
            )
            continue
        try:
            order = order_client.get_order(account.account_hash, broker_order_id)
            fill = _extract_schwab_fill(order, proposal)
            exit_targets = _exit_target_previews(
                proposal,
                fill["average_fill_price"],
                fill["filled_quantity"],
                target_percentages,
                stop_loss_percent=stop_loss_percent,
            )
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account.id,
                    account_label=account_label,
                    broker_order_id=broker_order_id,
                    status=fill["status"],
                    schwab_status=fill["schwab_status"],
                    filled_quantity=fill["filled_quantity"],
                    remaining_quantity=fill["remaining_quantity"],
                    average_fill_price=fill["average_fill_price"],
                    order_payload=order_payload,
                    exit_targets=exit_targets,
                    notes=fill["notes"],
                )
            )
        except (SchwabApiError, SchwabOAuthError, RuntimeError) as exc:
            statuses.append(
                ProposalOrderFillAccountStatus(
                    account_id=account.id,
                    account_label=account_label,
                    broker_order_id=broker_order_id,
                    status="error",
                    order_payload=order_payload,
                    notes=[f"Schwab order status lookup failed: {exc}"],
                )
            )

    notes: list[str] = []
    if not statuses:
        notes.append("No submitted Schwab entry orders were found in the local order audit for this proposal.")
    return ProposalOrderStatusResponse(
        proposal_id=proposal.id,
        generated_at=datetime.now(timezone.utc),
        account_statuses=statuses,
        has_filled_accounts=any(
            status.status in {"filled", "partial"} and status.average_fill_price for status in statuses
        ),
        notes=notes,
    )


def _send_exit_target_response(
    *,
    proposal: OptionProposal,
    target_index: int,
    request: SendExitTargetRequest,
    accounts: list,
    account_notes: list[str],
    order_status: ProposalOrderStatusResponse,
    order_client: SchwabMarketDataClient,
) -> SendProposalResponse:
    selected_ids = list(dict.fromkeys(request.selected_account_ids))
    if not selected_ids:
        return SendProposalResponse(
            status="blocked",
            proposal_id=proposal.id,
            selected_account_ids=[],
            notes=["Select at least one Schwab account before sending a closing order.", *account_notes],
        )

    accounts_by_id = {account.id: account for account in accounts if getattr(account, "enabled", False)}
    statuses_by_account = {status.account_id: status for status in order_status.account_statuses}
    live_gate_open = settings.service.live_gate_open
    results: list[AccountSendResult] = []

    for account_id in selected_ids:
        account = accounts_by_id.get(account_id)
        if account is None:
            results.append(
                AccountSendResult(
                    account_id=account_id,
                    account_label=account_id,
                    status="blocked",
                    reasons=["account_not_found_or_disabled"],
                )
            )
            continue

        fill_status = statuses_by_account.get(account.id)
        target = _target_preview_for_account(fill_status, target_index)
        reasons: list[str] = []
        order_payload = _schwab_exit_order_payload(proposal, target) if target is not None else None

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
        if _has_submitted_exit_order(proposal.id, account.id, target_index):
            reasons.append("target_exit_already_submitted")
        if not live_gate_open:
            reasons.append("live_orders_blocked")
        elif not request.confirm_live_order:
            reasons.append("live_order_confirmation_required")

        if any(reason not in {"live_orders_blocked", "live_order_confirmation_required"} for reason in reasons):
            results.append(
                AccountSendResult(
                    account_id=account.id,
                    account_label=_account_display_label(account),
                    status="blocked",
                    reasons=list(dict.fromkeys(reasons)),
                    order_payload=order_payload,
                )
            )
            continue

        if live_gate_open and request.confirm_live_order and order_payload is not None:
            try:
                placed = order_client.place_order(account.account_hash, order_payload)
                results.append(
                    AccountSendResult(
                        account_id=account.id,
                        account_label=_account_display_label(account),
                        status="submitted",
                        reasons=["schwab_exit_order_submitted"],
                        broker_order_id=str(placed.get("broker_order_id") or "") or None,
                        order_payload=order_payload,
                    )
                )
            except (SchwabApiError, SchwabOAuthError) as exc:
                results.append(
                    AccountSendResult(
                        account_id=account.id,
                        account_label=_account_display_label(account),
                        status="blocked",
                        reasons=[f"schwab_exit_order_submit_failed:{str(exc)[:200]}"],
                        order_payload=order_payload,
                    )
                )
        else:
            results.append(
                AccountSendResult(
                    account_id=account.id,
                    account_label=_account_display_label(account),
                    status="dry_run" if "live_orders_blocked" in reasons else "blocked",
                    reasons=list(dict.fromkeys(reasons or ["exit_order_payload_ready"])),
                    order_payload=order_payload,
                )
            )

    status = _aggregate_status(results)
    return SendProposalResponse(
        status=status,
        proposal_id=proposal.id,
        selected_account_ids=selected_ids,
        account_results=results,
        notes=[_send_exit_note(status), f"Exit target #{target_index + 1}"],
    )


def _target_preview_for_account(
    fill_status: ProposalOrderFillAccountStatus | None,
    target_index: int,
) -> ProposalExitTargetPreview | None:
    if fill_status is None:
        return None
    return next((target for target in fill_status.exit_targets if target.target_index == target_index), None)


def _schwab_exit_order_payload(proposal: OptionProposal, target: ProposalExitTargetPreview) -> dict:
    # Single-leg options with a protective stop become a true OCO bracket (LIMIT target
    # OCO STOP loss) so the resting exit covers both sides. Verticals/multi-leg and
    # stop-disabled (stop_trigger_price == 0) fall back to the legacy target-only SINGLE.
    if proposal.structure == "single" and target.stop_trigger_price > 0:
        return _schwab_single_option_oco_exit_payload(proposal, target)
    return {
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "NET_CREDIT" if proposal.structure == "debit_vertical" else "LIMIT",
        "complexOrderStrategyType": "VERTICAL" if proposal.structure == "debit_vertical" else "NONE",
        "quantity": target.qty,
        "price": f"{target.target_limit_price:.2f}",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": _schwab_exit_order_legs(proposal, target.qty),
    }


def _schwab_exit_order_legs(proposal: OptionProposal, quantity: int) -> list[dict]:
    return [
        {
            "instruction": "SELL_TO_CLOSE" if leg.action == "BUY" else "BUY_TO_CLOSE",
            "quantity": quantity,
            "instrument": {
                "symbol": leg.broker_symbol or fallback_broker_option_symbol(leg),
                "assetType": "OPTION",
            },
        }
        for leg in proposal.legs
    ]


def _schwab_single_option_oco_exit_payload(proposal: OptionProposal, target: ProposalExitTargetPreview) -> dict:
    order_legs = _schwab_exit_order_legs(proposal, target.qty)
    target_child = {
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "LIMIT",
        "complexOrderStrategyType": "NONE",
        "quantity": target.qty,
        "price": f"{target.target_limit_price:.2f}",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": order_legs,
    }
    stop_child = {
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "STOP",
        "complexOrderStrategyType": "NONE",
        "quantity": target.qty,
        "stopPrice": f"{target.stop_trigger_price:.2f}",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": order_legs,
    }
    return {
        "orderStrategyType": "OCO",
        "childOrderStrategies": [target_child, stop_child],
    }


def _exit_response_audit_event(
    response: SendProposalResponse,
    proposal: OptionProposal,
    target_index: int,
    order_status: ProposalOrderStatusResponse,
) -> dict:
    payload = response.model_dump(mode="json")
    payload["event_type"] = "proposal_exit_send_batch"
    payload["proposal"] = proposal.model_dump(mode="json")
    payload["target_index"] = target_index
    payload["order_status"] = order_status.model_dump(mode="json")
    return payload


def _has_submitted_exit_order(proposal_id: str, account_id: str, target_index: int) -> bool:
    for event in storage.list_order_events():
        if event.get("proposal_id") != proposal_id:
            continue
        if event.get("target_index") != target_index:
            continue
        account_results = event.get("account_results")
        if not isinstance(account_results, list):
            continue
        for result in account_results:
            if not isinstance(result, dict):
                continue
            if str(result.get("account_id") or "") != str(account_id):
                continue
            if result.get("status") == "submitted" and result.get("broker_order_id"):
                return True
    return False


def _submitted_entry_events_by_account(proposal_id: str) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for event in storage.list_order_events():
        if event.get("proposal_id") != proposal_id:
            continue
        result_events = _account_order_events(event)
        for result in result_events:
            if result.get("status") != "submitted" or not result.get("broker_order_id"):
                continue
            account_id = str(result.get("account_id") or "").strip()
            if not account_id:
                continue
            existing = latest.get(account_id)
            if existing is None or str(result.get("created_at") or "") >= str(existing.get("created_at") or ""):
                latest[account_id] = result
    return latest


def _account_order_events(event: dict) -> list[dict]:
    created_at = str(event.get("recorded_at") or event.get("created_at") or "")
    account_results = event.get("account_results")
    if isinstance(account_results, list):
        results: list[dict] = []
        for item in account_results:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "created_at": created_at,
                    "proposal_id": event.get("proposal_id"),
                    "account_id": item.get("account_id"),
                    "account_label": item.get("account_label"),
                    "status": item.get("status"),
                    "broker_order_id": item.get("broker_order_id"),
                    "order_payload": item.get("order_payload"),
                }
            )
        return results
    if event.get("event_type") == "proposal_send" and event.get("account_id"):
        return [
            {
                "created_at": created_at,
                "proposal_id": event.get("proposal_id"),
                "account_id": event.get("account_id"),
                "account_label": event.get("account_label"),
                "status": event.get("status"),
                "broker_order_id": event.get("broker_order_id"),
                "order_payload": event.get("order_payload"),
            }
        ]
    return []


def _parse_target_percentages(value: str | None) -> list[float]:
    if not value:
        return [20.0, 50.0, 60.0]
    parsed: list[float] = []
    for part in value.split(","):
        try:
            percent = float(part.strip())
        except ValueError:
            continue
        if percent > 0:
            parsed.append(percent)
    return parsed[:3] or [20.0, 50.0, 60.0]


def _proposal_build_settings(
    *,
    expiry_label: str | None,
    allow_itm: bool | None,
    max_loss: float | None,
    entry_offset_cents: float | None,
    target_percentages: str | None,
) -> ProposalBuildSettings:
    expiries = tuple(
        dict.fromkeys(
            item.upper().strip().replace(" ", "_")
            for item in (expiry_label or "").split(",")
            if item and item.strip()
        )
    )
    targets = tuple(_parse_target_percentages(target_percentages)) if target_percentages else ()
    entry_offset = None
    if entry_offset_cents is not None:
        entry_offset = round(float(entry_offset_cents) / 100, 4)
    return ProposalBuildSettings(
        expiry_labels=expiries,
        allow_in_the_money_primary=allow_itm,
        max_debit_per_trade=float(max_loss) if max_loss is not None else None,
        marketable_limit_offset=entry_offset,
        exit_target_percentages=targets,
    )


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
        for fill in execution_fills:
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
    if schwab_status == "REJECTED":
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
    target_percentages: list[float],
    *,
    stop_loss_percent: float = 0.0,
) -> list[ProposalExitTargetPreview]:
    if average_fill_price is None or filled_quantity <= 0:
        return []
    filled_contracts = max(0, int(math.floor(filled_quantity)))
    if filled_contracts <= 0:
        return []
    allocations = _exit_target_allocations(proposal, filled_contracts, target_percentages)
    # Protective stop applies only to single-leg options (the OCO bracket path). A STOP on a
    # NET_CREDIT vertical close is not supported here, so verticals stay target-only.
    #
    # Effective stop = the TIGHTER (more protective) of:
    #   (a) the configured percent stop (a guaranteed protection floor), and
    #   (b) the capped gamma-wall stop, only when NT_GEX_WALL_EXITS is on.
    # Higher stop premium = smaller loss = tighter, so we take max(). The gamma wall can only
    # pull the stop IN (exit earlier), never loosen it, and both are already capped at max loss.
    stop_price = 0.0
    if proposal.structure == "single":
        percent_stop = (
            _option_stop_trigger_price(average_fill_price, stop_loss_percent)
            if stop_loss_percent > 0
            else 0.0
        )
        gex_stop: float | None = None
        if (
            os.environ.get("NT_GEX_WALL_EXITS", "false").strip().lower() == "true"
            and proposal.gex_stop_loss_dollars
            and filled_contracts > 0
        ):
            gex_stop = protective_stop_premium(
                fill_price=float(average_fill_price),
                contracts=filled_contracts,
                stop_loss_dollars=float(proposal.gex_stop_loss_dollars),
                max_loss_dollars=float(proposal.max_loss or proposal.gex_stop_loss_dollars),
            )
        _stop_candidates = [s for s in (percent_stop, gex_stop) if s and s > 0]
        stop_price = max(_stop_candidates) if _stop_candidates else 0.0
    previews: list[ProposalExitTargetPreview] = []
    for target_index, quantity, target_percent in allocations:
        target_price = round(average_fill_price * (1 + target_percent / 100), 2)
        if proposal.structure == "debit_vertical" and proposal.width:
            target_price = min(target_price, round(float(proposal.width), 2))
        estimated_profit = round(max(0.0, (target_price - average_fill_price) * 100 * quantity), 2)
        previews.append(
            ProposalExitTargetPreview(
                target_index=target_index,
                qty=quantity,
                target_percent=round(float(target_percent), 4),
                entry_fill_price=round(float(average_fill_price), 4),
                target_limit_price=target_price,
                stop_loss_percent=round(float(stop_loss_percent), 4),
                stop_trigger_price=stop_price,
                estimated_profit=estimated_profit,
                tos_exit_order_line=_tos_exit_order_line_for_proposal(proposal, quantity, target_price),
                tos_stop_order_line=(
                    _tos_stop_order_line_for_proposal(proposal, quantity, stop_price)
                    if stop_price > 0
                    else ""
                ),
            )
        )
    return previews


def _exit_target_allocations(
    proposal: OptionProposal,
    filled_contracts: int,
    target_percentages: list[float],
) -> list[tuple[int, int, float]]:
    percentages = [percent for percent in target_percentages if percent > 0][: min(3, filled_contracts)]
    if not percentages:
        percentages = [target.target_percent for target in proposal.exit_targets if target.target_percent > 0][
            : min(3, filled_contracts)
        ]
    if not percentages:
        percentages = [25.0]
    remaining = filled_contracts
    allocations: list[tuple[int, int, float]] = []
    for index, percent in enumerate(percentages):
        quantity = remaining if index == len(percentages) - 1 else 1
        remaining -= quantity
        if quantity > 0:
            allocations.append((index, quantity, percent))
    return allocations


def _tos_exit_order_line_for_proposal(proposal: OptionProposal, quantity: int, limit_price: float) -> str:
    strikes = [leg.strike for leg in proposal.legs]
    structure = "VERTICAL" if proposal.structure == "debit_vertical" else "SINGLE"
    right = proposal.legs[0].right if proposal.legs else "CALL"
    strike_text = "/".join(_format_strike(strike) for strike in strikes)
    return (
        f"SELL -{quantity} {structure} {proposal.symbol.upper()} 100 "
        f"{proposal.expiry:%d %b %y} {strike_text} {right} @{limit_price:.2f} LMT GTC"
    ).upper()


def _tos_stop_order_line_for_proposal(proposal: OptionProposal, quantity: int, stop_price: float) -> str:
    strikes = [leg.strike for leg in proposal.legs]
    structure = "VERTICAL" if proposal.structure == "debit_vertical" else "SINGLE"
    right = proposal.legs[0].right if proposal.legs else "CALL"
    strike_text = "/".join(_format_strike(strike) for strike in strikes)
    return (
        f"SELL -{quantity} {structure} {proposal.symbol.upper()} 100 "
        f"{proposal.expiry:%d %b %y} {strike_text} {right} @{stop_price:.2f} STP GTC"
    ).upper()


def _option_stop_trigger_price(entry_fill_price: float, stop_loss_percent: float) -> float:
    percent = max(1.0, min(99.0, float(stop_loss_percent)))
    return max(0.01, round(float(entry_fill_price) * (1 - percent / 100), 2))


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


def _aggregate_status(results: list[AccountSendResult]) -> str:
    if results and all(result.status == "submitted" for result in results):
        return "submitted"
    if any(result.status == "dry_run" for result in results):
        return "dry_run"
    return "blocked"


def _send_note(status: str) -> str:
    if status == "submitted":
        return "Schwab order submission was attempted for every eligible selected account."
    if status == "dry_run":
        return "Order payloads were prepared only; live execution gates are not all open."
    return "No Schwab order was submitted. Review account-level reasons."


def _send_exit_note(status: str) -> str:
    if status == "submitted":
        return "Schwab closing order submission was attempted for every filled selected account."
    if status == "dry_run":
        return "Closing order payloads were prepared only; live execution gates are not all open."
    return "No Schwab closing order was submitted. Review account-level reasons."


def _is_simulated_proposal(proposal) -> bool:
    return proposal.id.startswith("sim_") or "SIM_ONLY" in set(proposal.reasons)


def _parse_replay_as_of(value: str | None) -> datetime:
    tz = ZoneInfo(settings.scanner.timezone)
    if value is None or not value.strip():
        replay_day = _previous_weekday(datetime.now(tz).date())
        return datetime.combine(replay_day, time(9, 29), tzinfo=tz).astimezone(timezone.utc)

    raw = value.strip()
    if len(raw) == 10:
        replay_day = date_type.fromisoformat(raw)
        return datetime.combine(replay_day, time(9, 29), tzinfo=tz).astimezone(timezone.utc)

    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def _previous_weekday(day: date_type) -> date_type:
    candidate = day - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate
