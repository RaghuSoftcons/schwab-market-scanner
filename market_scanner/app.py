from __future__ import annotations

import asyncio
import json
import math
import re
import time as _time  # the bare name `time` is datetime.time (imported below); _time is the stdlib module
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import os

from nt_schwab_bridge.auth import (
    AuthConfig,
    UserStore,
    render_login_html,
    set_current_trader,
    sign_session,
    verify_machine_key,
    verify_session,
)
from nt_schwab_bridge.automation import AutomationConfig, AutomationEngine, Tier
from nt_schwab_bridge.config import BridgeConfig, RiskConfig, ServiceConfig
from nt_schwab_bridge.dashboard_settings import DEFAULT_STOP_LOSS_PERCENT, DashboardSettingsStore
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
    CloseContractRequest,
    PositionsResponse,
    PositionRow,
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
from market_scanner import trailing


settings_load = load_settings()
settings: AppSettings = settings_load.settings
storage = ScannerStorage(settings.storage.path)
scanner = MarketScanner(settings)
trade_log_store = TradeLogStore(settings.storage.path / "trades.jsonl")
_scheduler_task: asyncio.Task | None = None
_trailing_task: asyncio.Task | None = None

# Realized-P&L sync lookback (days). Schwab transactions older than this are not re-scanned.
_PNL_SYNC_LOOKBACK_DAYS = 14

# Automation tiers (#7). Tier 1 manual -> Tier 2 auto-queue w/ cancel window -> Tier 3 autopilot.
# These NEVER relax the live-order triple-lock or confirm_live_order; they sit on top of it.
automation_config = AutomationConfig.from_env()
automation_engine = AutomationEngine(automation_config)
kill_switch: dict = {"engaged": False, "reason": ""}

# Positions sent live from THIS dashboard (keyed by underlying symbol); the ones shown for
# Close-now. Persisted to disk so they survive restarts/redeploys (needs a persistent volume at
# the storage path; otherwise it only survives in-process).
_ACTIVE_POSITIONS_PATH = settings.storage.path / "active_positions.json"


def _save_active_positions() -> None:
    try:
        _ACTIVE_POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ACTIVE_POSITIONS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(active_positions, indent=2), encoding="utf-8")
        os.replace(tmp, _ACTIVE_POSITIONS_PATH)  # atomic; readers never see a partial file
    except OSError:
        pass  # best-effort; never let persistence break a send/close


def _load_active_positions() -> dict[str, dict]:
    try:
        if _ACTIVE_POSITIONS_PATH.exists():
            data = json.loads(_ACTIVE_POSITIONS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


active_positions: dict[str, dict] = _load_active_positions()

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


def _has_pending_arms() -> bool:
    """True if any tracked position still has an un-armed account under active stop management."""
    for entry in active_positions.values():
        if not isinstance(entry, dict):
            continue
        sm = entry.get("stop_mgmt")
        if not isinstance(sm, dict) or str(sm.get("mode") or "fixed") == "fixed":
            continue
        hashes = entry.get("account_hashes") or {}
        hlist = list(hashes.values()) if isinstance(hashes, dict) else list(hashes)
        armed = set(sm.get("armed_hashes") or [])
        if any(h and h not in armed for h in hlist):
            return True
    return False


async def _trailing_monitor_loop() -> None:
    """Poll live prices and arm breakeven/trailing stops for scanner-sent single-leg positions.

    Adaptive cadence: fast (trail_poll_seconds, min 1s) while any position is pending arm; slow
    (30s) when idle. Only acts when the live gate is open — arming cancels+places real orders.
    Mirrors the Unified nt-bridge-v2 trailing monitor; the arm logic lives in market_scanner.trailing.
    """
    await asyncio.sleep(8)  # let the app settle before the first poll
    while True:
        poll_s = 30.0
        try:
            if _has_pending_arms() and settings.service.live_gate_open:
                sm_cfg = _dashboard_settings.get_stop_mgmt()
                poll_s = max(1.0, float(sm_cfg.get("trail_poll_seconds") or 4))
                await asyncio.to_thread(
                    trailing.evaluate_trailing_arms,
                    active_positions=active_positions,
                    make_client=lambda: SchwabMarketDataClient(settings.schwab),
                    avg_mark_fn=_position_avg_mark_pnl,
                    save_positions=_save_active_positions,
                    now_utc=datetime.now(timezone.utc),
                    log=None,
                )
        except Exception:
            pass  # never let a monitor error kill the loop
        await asyncio.sleep(poll_s)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _scheduler_task, _trailing_task
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    _trailing_task = asyncio.create_task(_trailing_monitor_loop())
    try:
        yield
    finally:
        for task in (_scheduler_task, _trailing_task):
            if task is not None:
                task.cancel()


app = FastAPI(title="Schwab Market Scanner", version="0.1.0", lifespan=lifespan)

# --- Dashboard authentication (multi-trader login), ported from nt-bridge-v2 ---
# OFF by default (local unchanged). Enable on Railway with DASHBOARD_AUTH_ENABLED=true.
# Browsers must log in (session cookie); machine callers (e.g. GPT actions) bypass via the
# EXISTING shared X-API-Key (settings.service.api_key), so nothing machine-facing breaks.
_auth_config = AuthConfig.from_env()
_user_store = UserStore(_auth_config.users_file, users_json=_auth_config.users_json)
# Open (no session needed): health check, the login pages, and the keyed mobile kill switch.
_AUTH_OPEN_PATHS = {"/health", "/login", "/logout", "/favicon.ico", "/automation/kill"}


@app.middleware("http")
async def _dashboard_auth(request: Request, call_next):
    cfg = _auth_config
    if not cfg.enabled:
        set_current_trader("")  # attribution resolves to the owner name
        return await call_next(request)
    path = request.url.path
    if path in _AUTH_OPEN_PATHS or path.startswith("/static/"):
        return await call_next(request)
    # Machine callers (GPT actions, etc.) present the shared X-API-Key -> allowed, no session.
    api_key = settings.service.api_key.strip()
    if api_key and verify_machine_key(request.headers.get("x-api-key", ""), api_key):
        set_current_trader(cfg.owner_name)
        return await call_next(request)
    if cfg.misconfigured:  # enabled but no signing secret -> fail CLOSED, never serve open
        return JSONResponse(
            {"detail": "Dashboard auth is enabled but DASHBOARD_SESSION_SECRET is not set."},
            status_code=503,
        )
    username = verify_session(request.cookies.get(cfg.cookie_name, ""), cfg.secret)
    if not username:
        accept = request.headers.get("accept", "")
        if request.method == "GET" and "text/html" in accept:
            return RedirectResponse(url="/login", status_code=303)
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    set_current_trader(username)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_page(error: str = "") -> HTMLResponse:
    return HTMLResponse(render_login_html(error=bool(error)), headers={"Cache-Control": "no-store"})


@app.post("/login")
async def login_submit(request: Request):
    from urllib.parse import parse_qs

    raw = (await request.body()).decode("utf-8", "replace")
    form = parse_qs(raw, keep_blank_values=True)
    username = (form.get("username", [""])[0] or "").strip()
    password = form.get("password", [""])[0] or ""
    canonical = _user_store.verify(username, password)
    if not canonical or not _auth_config.secret:
        return RedirectResponse(url="/login?error=1", status_code=303)
    token = sign_session(canonical, _auth_config.secret, ttl_seconds=_auth_config.session_ttl_seconds)
    resp = RedirectResponse(url="/dashboard", status_code=303)
    resp.set_cookie(
        _auth_config.cookie_name, token, max_age=_auth_config.session_ttl_seconds,
        httponly=True, secure=_auth_config.cookie_secure, samesite="lax", path="/",
    )
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(_auth_config.cookie_name, path="/")
    return resp


@app.get("/whoami")
async def whoami() -> dict:
    from nt_schwab_bridge.auth import current_trader_name

    trader = current_trader_name(default=_auth_config.owner_name)
    return {
        "trader": trader,
        "display_name": _user_store.display_name(trader) or trader,
        "auth_enabled": _auth_config.enabled,
    }


# --- Durable dashboard settings (ported from nt-bridge-v2) --------------------
# Backs SL %, OCO/OTOCO, targets, entry offset, expiry, and stop-management so the
# controls persist and drive the order payload (Phase 1 of LOOKFEEL_PARITY_PLAN.md).
# Forces stop_loss_percent=50 on startup (never carry "No SL"), like the Unified dashboard.
_dashboard_settings = DashboardSettingsStore(".local_state/dashboard_settings.json")


def _dashboard_settings_dict() -> dict:
    s = _dashboard_settings
    sm = s.get_stop_mgmt()
    return {
        "max_loss_dollars": s.get_max_loss_dollars(), "max_loss_choices": s.max_loss_choices,
        "entry_offset_cents": s.get_entry_offset_cents(), "entry_offset_choices": s.entry_offset_choices,
        "expiry_label": s.get_expiry_label(), "expiry_choices": s.expiry_choices,
        "target_percentages": s.get_target_percentages(),
        "stop_loss_percent": s.get_stop_loss_percent(), "stop_loss_percent_choices": s.stop_loss_percent_choices,
        "allow_itm": s.get_allow_itm(), "close_on_reversal": s.get_close_on_reversal(), "otoco": s.get_otoco(),
        "stop_mode": s.get_stop_mode(), "stop_mode_choices": s.stop_mode_choices,
        "trail_start_percent": sm.get("trail_start_percent"),
        "trail_distance_percent": sm.get("trail_distance_percent"),
        "trail_poll_seconds": sm.get("trail_poll_seconds"),
    }


@app.get("/dashboard/settings")
async def get_dashboard_settings() -> dict:
    return _dashboard_settings_dict()


@app.post("/dashboard/settings")
async def update_dashboard_settings(payload: dict = Body(...), _: None = Depends(_require_api_key)) -> dict:
    s = _dashboard_settings
    setters = {
        "max_loss_dollars": s.set_max_loss_dollars,
        "entry_offset_cents": s.set_entry_offset_cents,
        "expiry_label": s.set_expiry_label,
        "target_percentages": s.set_target_percentages,
        "stop_loss_percent": s.set_stop_loss_percent,
        "allow_itm": s.set_allow_itm,
        "close_on_reversal": s.set_close_on_reversal,
        "otoco": s.set_otoco,
        "stop_mgmt": s.set_stop_mgmt,
    }
    try:
        for key, fn in setters.items():
            if key in payload:
                fn(payload[key])
        # Also accept flat stop-management fields (stop_mode / trail_*).
        flat = {k: payload[k] for k in ("stop_mode", "trail_start_percent", "trail_distance_percent", "trail_poll_seconds") if k in payload}
        if flat:
            s.set_stop_mgmt(flat)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid dashboard setting: {exc}")
    return _dashboard_settings_dict()


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
async def dashboard() -> HTMLResponse:
    # Pass the configured API key so the dashboard authenticates protected POSTs when one is set.
    # no-store: the dashboard JS is inlined, so a cached page hides new deploys -- never cache it.
    return HTMLResponse(
        dashboard_html(api_key=settings.service.api_key),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/schwab/status")
async def schwab_status() -> dict:
    return schwab_market_data_status(_bridge_config()).model_dump(mode="json")


def _resolve_account_alias(account_id: str) -> str | None:
    """Resolve an alias from an account id/number. Handles the 'schwab_<number>' id form by
    extracting digits, then exact- or unique-suffix-matching ACCOUNT_ALIASES (keyed by number)."""
    digits = "".join(ch for ch in str(account_id) if ch.isdigit())
    if not digits:
        return None
    if digits in ACCOUNT_ALIASES:
        return ACCOUNT_ALIASES[digits]
    matches = [alias for number, alias in ACCOUNT_ALIASES.items() if len(digits) >= 4 and number.endswith(digits)]
    return matches[0] if len(matches) == 1 else None


def _account_alias(account_id: str) -> str:
    """Display label = the friendly ALIAS only (e.g. 'Individual', 'Grow Fly'). Falls back to the
    bare account number, then the raw id, when no alias is known. (Raghu: drop the number prefix.)"""
    alias = _resolve_account_alias(account_id)
    if alias:
        return alias
    digits = "".join(ch for ch in str(account_id) if ch.isdigit())
    return digits or str(account_id)


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
    """Sync realized P&L from Schwab transactions (14-day lookback, deduped) and return the summary.
    Also refreshes the order#-based spread structure on this cadence (best-effort)."""
    result = await asyncio.to_thread(_sync_schwab_pnl)
    try:
        await asyncio.to_thread(_sync_spread_structure)
    except Exception:  # noqa: BLE001 -- spread structure is an enhancement; never fail the P&L sync
        pass
    return result


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

def _registration_stop_mgmt(
    proposal: OptionProposal, otoco_applied: bool, target_percentages: list[float],
    stop_mode: str, trail_start_percent: float, trail_distance_percent: float, stop_loss_percent: float,
) -> dict | None:
    """Capture active-stop intent at SEND time so the trailing monitor can arm it later.

    Only single-leg OTOCO entries with a real protective stop arm — verticals, a plain (non-OTOCO)
    entry, a disabled stop, or 'fixed' mode return None (the resting fixed OCO is left as-is). The
    dict is frozen at send time so a later dashboard settings change can't retroactively alter a
    live position's management. Mirrors the Unified nt-bridge-v2 _registration_stop_mgmt."""
    mode = (stop_mode or "fixed").strip().lower()
    if mode not in ("breakeven", "trailing", "be_then_trail"):
        return None
    if not otoco_applied or proposal.structure != "single" or len(proposal.legs) != 1:
        return None
    if not stop_loss_percent or stop_loss_percent <= 0:
        return None  # no fixed stop to replace → nothing to arm
    first_target = float(target_percentages[0]) if target_percentages else 0.0
    return {
        "mode": mode,
        "start_pct": float(trail_start_percent or 0),
        "trail_pct": float(trail_distance_percent or 0),
        "target_pct": first_target,
        "armed_hashes": [],
        "arm_fails": {},
    }


def _register_active_position(proposal: OptionProposal, account_ids: list[str], accounts_by_id: dict, broker_order_ids: dict, stop_mgmt: dict | None = None) -> None:
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
        "stop_mgmt": stop_mgmt,
    }
    _save_active_positions()


def _pos_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _position_avg_mark_pnl(raw: dict) -> tuple[float | None, float | None, float | None]:
    """(avg, mark, unrealized) for a raw Schwab option position, matching thinkorswim.

    AVG-FIELD TRAP: use averageLongPrice / averageShortPrice (the ACTUAL average trade price,
    matches TOS) — NOT averagePrice, which can be a tax-lot-adjusted basis (e.g. a wash-sale
    short showed averagePrice 28.71 vs the real fill 53.72). When the trade price differs from
    that basis, Schwab's long/shortOpenProfitLoss is built on the basis, so we recompute
    unrealized from (mark - avg) to stay consistent with the avg we display; otherwise we use
    Schwab's open P&L verbatim. Multiplier 100 for options."""
    inst = raw.get("instrument") if isinstance(raw.get("instrument"), dict) else {}
    mult = 100.0 if str((inst or {}).get("assetType", "")) == "OPTION" else 1.0
    long_q = _pos_float(raw.get("longQuantity"))
    short_q = _pos_float(raw.get("shortQuantity"))
    net = long_q - short_q
    mv = _pos_float(raw.get("marketValue"))
    mark = round(mv / (net * mult), 2) if net else None
    tax_lot_basis = _pos_float(raw.get("averagePrice")) or None
    if long_q:
        avg = _pos_float(raw.get("averageLongPrice")) or None
        schwab_pl = _pos_float(raw.get("longOpenProfitLoss"))
    else:
        avg = _pos_float(raw.get("averageShortPrice")) or None
        schwab_pl = _pos_float(raw.get("shortOpenProfitLoss"))
    if avg is None:
        avg = tax_lot_basis
    if avg is not None and mark is not None and tax_lot_basis is not None and abs(avg - tax_lot_basis) > 0.005:
        unrealized = round((mark - avg) * mult * net, 2)
    else:
        unrealized = round(schwab_pl, 2)
    return avg, mark, unrealized


def _row_from_raw(account_id: str, raw: dict, is_spread: bool) -> PositionRow:
    """Build a table row from a raw Schwab position dict (ACCOUNT/SYMBOL/QTY/AVG/MARK/UNREALIZED)."""
    inst = raw.get("instrument") if isinstance(raw.get("instrument"), dict) else {}
    broker_symbol = str((inst or {}).get("symbol", "") or "")
    net = _pos_float(raw.get("longQuantity")) - _pos_float(raw.get("shortQuantity"))
    avg, mark, upnl = _position_avg_mark_pnl(raw)
    parsed = _parse_broker_option_symbol(broker_symbol)
    underlying = parsed[0] if parsed else str((inst or {}).get("underlyingSymbol", "") or "")
    return PositionRow(
        account_id=account_id,
        account_label=_account_alias(account_id),
        symbol=broker_symbol,
        underlying=underlying,
        qty=net,
        avg=avg,
        mark=mark,
        unrealized_pnl=upnl,
        direction="long" if net > 0 else "short",
        closeable=(not is_spread and net != 0),
        is_spread=is_spread,
        source="schwab",
    )


# ----- Open Positions panel: spread detection + order#-based reconstruction (ported from -----
# nt-bridge-v2). These operate on normalized position dicts (keys: symbol, underlying, quantity
# [signed], average_price, mark, market_value, asset_type, unrealized_pnl) so the reference logic
# ports verbatim; _all_positions_response builds those dicts then converts to PositionRow.

_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "REPLACED"}
_SPREAD_STRUCTURE_LOOKBACK_DAYS = 180
_SPREAD_STRUCTURE_PATH = settings.storage.path / "spread_structure.json"


def _parse_osi(symbol: str) -> tuple[str, str, float | None]:
    """(expiry YYMMDD, right C/P, strike) from an OSI option symbol; strike None if unparseable."""
    compact = str(symbol or "").replace(" ", "")
    if len(compact) < 15:
        return "", "", None
    expiry = compact[-15:-9]
    right = compact[-9:-8]
    try:
        strike = int(compact[-8:]) / 1000.0
    except ValueError:
        strike = None
    return expiry, right, strike


def _tag_iron_condors(positions: list) -> None:
    """Tag an IRON CONDOR / IRON FLY: a PUT vertical + a CALL vertical at the same underlying/expiry
    with equal quantity (4 legs spanning BOTH rights). Iron fly = the two SHORT strikes are equal.
    Conservative: only fires on exactly one clean long+short put pair AND one clean long+short call
    pair of equal magnitude. Mutates in place."""
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for pos in positions:
        if pos.get("from_structure") or pos.get("is_spread_leg"):
            continue
        expiry, right, strike = _parse_osi(pos.get("symbol", ""))
        if strike is None or right not in ("C", "P"):
            continue
        groups[(pos.get("underlying"), expiry)].append((right, strike, pos))

    def _vertical(pair):
        (s_a, p_a), (s_b, p_b) = pair
        qa = p_a.get("quantity") or 0
        qb = p_b.get("quantity") or 0
        if qa == 0 or qb == 0 or abs(abs(qa) - abs(qb)) > 1e-9 or (qa > 0) == (qb > 0):
            return None
        return {
            "qty": abs(qa),
            "long": p_a if qa > 0 else p_b,
            "short": p_b if qa > 0 else p_a,
            "short_strike": s_b if qa > 0 else s_a,
        }

    for (underlying, expiry), items in groups.items():
        puts = [(s, p) for r, s, p in items if r == "P"]
        calls = [(s, p) for r, s, p in items if r == "C"]
        if len(puts) != 2 or len(calls) != 2:
            continue
        pv, cv = _vertical(puts), _vertical(calls)
        if not pv or not cv or abs(pv["qty"] - cv["qty"]) > 1e-9:
            continue
        kind = "iron_fly" if abs(pv["short_strike"] - cv["short_strike"]) < 1e-9 else "iron_condor"
        spread_id = f"{underlying}|IC|{expiry}|{pv['short_strike']:g}-{cv['short_strike']:g}"
        for leg in (pv["long"], pv["short"], cv["long"], cv["short"]):
            leg["is_spread_leg"] = True
            leg["spread_id"] = spread_id
            leg["spread_kind"] = kind


def _tag_condors(positions: list) -> None:
    """Tag a CONDOR (same underlying/expiry/right, 4 legs): two outer wings of one sign + two inner
    legs of the opposite sign, all equal magnitude N at strikes K1<K2<K3<K4. Conservative; only
    clean unclaimed single-position strikes. Mutates in place."""
    from collections import defaultdict

    groups: dict = defaultdict(dict)
    for pos in positions:
        if pos.get("from_structure") or pos.get("is_spread_leg"):
            continue
        expiry, right, strike = _parse_osi(pos.get("symbol", ""))
        if strike is None:
            continue
        groups[(pos.get("underlying"), expiry, right)].setdefault(strike, []).append(pos)
    for (underlying, expiry, right), by_strike in groups.items():
        avail = sorted(s for s, ps in by_strike.items() if len(ps) == 1 and not ps[0].get("is_spread_leg"))
        used: set = set()
        for a in range(len(avail)):
            k1 = avail[a]
            if k1 in used:
                continue
            q1 = by_strike[k1][0].get("quantity") or 0
            if q1 == 0:
                continue
            for d in range(len(avail) - 1, a + 2, -1):  # k4 leaves room for two inner strikes
                k4 = avail[d]
                if k4 in used or abs((by_strike[k4][0].get("quantity") or 0) - q1) > 1e-9:
                    continue
                inner = [s for s in avail if k1 < s < k4 and s not in used
                         and abs((by_strike[s][0].get("quantity") or 0) + q1) < 1e-9]
                if len(inner) >= 2:
                    k2, k3 = inner[0], inner[-1]
                    spread_id = f"{underlying}|COND|{right}|{k1:g}-{k2:g}-{k3:g}-{k4:g}"
                    for s in (k1, k2, k3, k4):
                        leg = by_strike[s][0]
                        leg["is_spread_leg"] = True
                        leg["spread_id"] = spread_id
                        leg["spread_kind"] = "condor"
                    used.update([k1, k2, k3, k4])
                    break


def _mark_spread_legs(positions: list) -> None:
    """Tag multi-leg structures with a shared `spread_id` (+ spread_kind) so they combine into one
    line and aren't mis-flagged as aggregated. Claims larger / cross-right structures FIRST (iron
    condor/fly, condor, butterfly) so their legs aren't split into verticals, then pairs the rest:
    verticals (nearest short↔long, equal-qty), then calendars (same strike, different expiry). A
    qty-mismatch vertical leg is flagged spread_aggregated (Schwab blended the strike). Skips rows
    already grouped by the order#-based reconstruction. Mutates in place."""
    for pos in positions:
        if pos.get("from_structure"):
            continue  # already grouped by the order#-based reconstruction; don't re-pair
        pos["is_spread_leg"] = False
        pos.pop("spread_id", None)
        pos.pop("spread_aggregated", None)
        pos.pop("spread_kind", None)

    # Larger / cross-right structures BEFORE the 2-leg vertical pairing: 4-leg (iron condor/fly,
    # condor) -> 3-leg butterfly.
    _tag_iron_condors(positions)
    _tag_condors(positions)

    # Butterfly pass: claim a 1:2:1 (N:2N:N) fly. Body = 2N at mid, wings = N at a low + a high strike
    # of the OPPOSITE sign. EQUIDISTANT wings -> "butterfly"; otherwise "broken_wing". One spread_id
    # for all three legs. Only unclaimed single-position strikes.
    fly_by_group: dict = {}
    for pos in positions:
        if pos.get("from_structure") or pos.get("is_spread_leg"):
            continue
        expiry, right, strike = _parse_osi(pos.get("symbol", ""))
        if strike is None:
            continue
        fly_by_group.setdefault((pos.get("underlying"), expiry, right), {}).setdefault(strike, []).append(pos)
    for (underlying, expiry, right), by_strike in fly_by_group.items():
        strikes = sorted(s for s, ps in by_strike.items() if len(ps) == 1)
        claimed: set = set()
        for mid in strikes:
            if mid in claimed:
                continue
            body = by_strike[mid][0]
            body_qty = body.get("quantity") or 0
            if body_qty == 0 or abs(body_qty) % 2 != 0:
                continue  # body must be an even quantity (2N)
            wing_qty = -body_qty / 2  # opposite sign, half the magnitude
            lows = [s for s in strikes if s < mid and s not in claimed
                    and abs((by_strike[s][0].get("quantity") or 0) - wing_qty) < 1e-9]
            highs = [s for s in strikes if s > mid and s not in claimed
                     and abs((by_strike[s][0].get("quantity") or 0) - wing_qty) < 1e-9]
            if not lows or not highs:
                continue
            chosen = next(((lw, 2 * mid - lw) for lw in lows if (2 * mid - lw) in highs), None)
            kind = "butterfly"
            if chosen is None:
                chosen, kind = (lows[-1], highs[0]), "broken_wing"  # nearest low + nearest high
            low, high = chosen
            spread_id = f"{underlying}|FLY|{right}|{low:g}-{mid:g}-{high:g}"
            for leg in (by_strike[low][0], body, by_strike[high][0]):
                leg["is_spread_leg"] = True
                leg["spread_id"] = spread_id
                leg["spread_kind"] = kind
            claimed.update([low, mid, high])

    groups: dict = {}
    for pos in positions:
        if pos.get("from_structure") or pos.get("is_spread_leg"):
            continue  # already claimed by a multi-leg pass above
        expiry, right, strike = _parse_osi(pos.get("symbol", ""))
        if strike is None:
            continue
        groups.setdefault((pos.get("underlying"), expiry, right), []).append((strike, pos))
    for (underlying, expiry, right), items in groups.items():
        longs = sorted(((s, p) for s, p in items if (p.get("quantity") or 0) > 0), key=lambda t: t[0])
        shorts = sorted(((s, p) for s, p in items if (p.get("quantity") or 0) < 0), key=lambda t: t[0])
        used: set = set()
        for short_strike, short_pos in shorts:
            best_i = best_d = None
            for i, (long_strike, _lp) in enumerate(longs):
                if i in used:
                    continue
                dist = abs(long_strike - short_strike)
                if best_d is None or dist < best_d:
                    best_d, best_i = dist, i
            if best_i is None:
                continue
            long_strike, long_pos = longs[best_i]
            long_qty = abs(long_pos.get("quantity") or 0)
            short_qty = abs(short_pos.get("quantity") or 0)
            short_pos["is_spread_leg"] = True
            long_pos["is_spread_leg"] = True
            if abs(long_qty - short_qty) < 1e-9:
                used.add(best_i)
                spread_id = f"{underlying}|{expiry}|{right}|{long_strike:g}-{short_strike:g}"
                short_pos["spread_id"] = spread_id
                long_pos["spread_id"] = spread_id
            else:
                short_pos["spread_aggregated"] = True
                long_pos["spread_aggregated"] = True

    # Calendar pass: pair a SHORT with a LONG of the SAME underlying/right/STRIKE but a DIFFERENT
    # expiry. Only legs the vertical pass left unpaired, only a clean 1:1 quantity match.
    cal_groups: dict = {}
    for pos in positions:
        if pos.get("from_structure") or pos.get("is_spread_leg"):
            continue
        expiry, right, strike = _parse_osi(pos.get("symbol", ""))
        if strike is None:
            continue
        cal_groups.setdefault((pos.get("underlying"), right, strike), []).append((expiry, pos))
    for (underlying, right, strike), items in cal_groups.items():
        longs = [(e, p) for e, p in items if (p.get("quantity") or 0) > 0]
        used = set()
        for short_exp, short_pos in [(e, p) for e, p in items if (p.get("quantity") or 0) < 0]:
            short_qty = abs(short_pos.get("quantity") or 0)
            match_i = next(
                (i for i, (long_exp, long_pos) in enumerate(longs)
                 if i not in used and long_exp != short_exp
                 and abs(abs(long_pos.get("quantity") or 0) - short_qty) < 1e-9),
                None,
            )
            if match_i is None:
                continue
            used.add(match_i)
            long_exp, long_pos = longs[match_i]
            spread_id = f"{underlying}|CAL|{right}|{strike:g}|{short_exp}-{long_exp}"
            for leg in (short_pos, long_pos):
                leg["is_spread_leg"] = True
                leg["spread_id"] = spread_id
                leg["spread_kind"] = "calendar"


def _reconstruct_orders_from_transactions(transactions) -> dict:
    """Group OPENING option fills by order id to recover per-spread structure Schwab's AGGREGATED
    positions feed loses. 2-leg vertical order -> a spread def (each leg's real fill); 1-leg -> a
    single def. Excludes RECEIVE_AND_DELIVER (assignment/expiration/transfer $0 legs).
    Returns {"spreads": [...], "singles": [...]}."""
    from collections import defaultdict

    by_order: dict = defaultdict(list)
    for txn in transactions:
        if not isinstance(txn, dict):
            continue
        if str(txn.get("type") or "").upper() != "TRADE":
            continue
        order_id = txn.get("orderId") or txn.get("orderNumber") or txn.get("activityId")
        if order_id is None:
            continue
        for item in (txn.get("transferItems") or []):
            instrument = item.get("instrument") or {}
            if str(instrument.get("assetType") or "") != "OPTION":
                continue
            effect = str(item.get("positionEffect") or "").upper()
            if effect and effect != "OPENING":
                continue
            symbol = str(instrument.get("symbol") or "").replace(" ", "")
            amount = _to_float_or_none(item.get("amount"))
            price = _to_float_or_none(item.get("price"))
            if not symbol or amount is None or price is None:
                continue
            by_order[order_id].append({
                "symbol": symbol, "amount": amount, "price": price,
                "underlying": instrument.get("underlyingSymbol") or "",
            })

    spreads: list = []
    singles: list = []
    for order_id, legs in by_order.items():
        if len(legs) == 1:
            leg = legs[0]
            singles.append({
                "symbol": leg["symbol"], "fill": round(leg["price"], 4),
                "qty": abs(leg["amount"]), "order_id": str(order_id),
            })
            continue
        if len(legs) != 2:
            continue
        longs = [item for item in legs if item["amount"] > 0]
        shorts = [item for item in legs if item["amount"] < 0]
        if len(longs) != 1 or len(shorts) != 1:
            continue
        long_leg, short_leg = longs[0], shorts[0]
        long_exp, long_right, long_strike = _parse_osi(long_leg["symbol"])
        short_exp, short_right, short_strike = _parse_osi(short_leg["symbol"])
        if long_exp != short_exp or long_right != short_right or long_strike is None or short_strike is None:
            continue
        spreads.append({
            "underlying": long_leg["underlying"] or short_leg["underlying"],
            "expiry": long_exp, "right": long_right,
            "long_symbol": long_leg["symbol"], "short_symbol": short_leg["symbol"],
            "long_strike": long_strike, "short_strike": short_strike,
            "long_fill": round(long_leg["price"], 4), "short_fill": round(short_leg["price"], 4),
            "qty": min(abs(long_leg["amount"]), abs(short_leg["amount"])),
            "order_id": str(order_id),
        })
    return {"spreads": spreads, "singles": singles}


def _apply_spread_structure(positions: list, structure: dict) -> list:
    """Rebuild AGGREGATED positions into per-order pieces using order#-grouped `structure`, so a
    strike shared across spreads/singles shows as its real pieces. Spread legs get a shared
    spread_id=ord-<id>; per-piece unrealized recomputed from each piece's fill + live mark.
    Returns a NEW list (aggregated originals replaced)."""
    spreads = (structure or {}).get("spreads") or []
    singles = (structure or {}).get("singles") or []
    pos_by_sym: dict = {}
    remaining: dict = {}
    for pos in positions:
        compact = str(pos.get("symbol") or "").replace(" ", "")
        pos_by_sym[compact] = pos
        remaining[compact] = remaining.get(compact, 0.0) + (pos.get("quantity") or 0.0)

    def make_row(template: dict, qty: float, avg, spread_id=None) -> dict:
        multiplier = 100.0 if str(template.get("asset_type")) == "OPTION" else 1.0
        mark = template.get("mark")
        row = dict(template)
        row["quantity"] = qty
        row["average_price"] = avg
        row["market_value"] = (mark * multiplier * qty) if mark is not None else template.get("market_value")
        row["unrealized_pnl"] = ((mark - avg) * multiplier * qty) if (mark is not None and avg is not None) else None
        row["from_structure"] = bool(spread_id)
        row["is_spread_leg"] = bool(spread_id)
        row.pop("spread_aggregated", None)
        if spread_id:
            row["spread_id"] = spread_id
        else:
            row.pop("spread_id", None)
        return row

    out: list = []
    for spread in spreads:
        long_sym = str(spread.get("long_symbol") or "").replace(" ", "")
        short_sym = str(spread.get("short_symbol") or "").replace(" ", "")
        if long_sym not in pos_by_sym or short_sym not in pos_by_sym:
            continue
        count = min(spread.get("qty") or 0.0, remaining.get(long_sym, 0.0), -remaining.get(short_sym, 0.0))
        if count <= 0:
            continue
        remaining[long_sym] -= count
        remaining[short_sym] += count
        spread_id = f"ord-{spread.get('order_id')}"
        out.append(make_row(pos_by_sym[long_sym], count, spread.get("long_fill"), spread_id))
        out.append(make_row(pos_by_sym[short_sym], -count, spread.get("short_fill"), spread_id))

    for single in singles:
        compact = str(single.get("symbol") or "").replace(" ", "")
        held = remaining.get(compact, 0.0)
        if compact not in pos_by_sym or abs(held) < 1e-9:
            continue
        sign = 1.0 if held > 0 else -1.0
        count = min(single.get("qty") or 0.0, abs(held))
        if count <= 0:
            continue
        remaining[compact] -= sign * count
        out.append(make_row(pos_by_sym[compact], sign * count, single.get("fill")))

    for compact, qty in remaining.items():
        if abs(qty) < 1e-9:
            continue
        pos = pos_by_sym[compact]
        out.append(make_row(pos, qty, pos.get("average_price")))
    return out


def _cancelable_order_ids_for_symbol(orders: list, osi_symbol: str) -> list:
    """Top-level order ids (still cancelable) whose legs reference the given option symbol
    (recurses OCO/TRIGGER children — so OTOCO brackets are caught)."""
    target = str(osi_symbol or "").replace(" ", "")

    def references(order: dict) -> bool:
        for leg in (order.get("orderLegCollection") or []):
            if str((leg.get("instrument") or {}).get("symbol", "")).replace(" ", "") == target:
                return True
        return any(references(ch) for ch in (order.get("childOrderStrategies") or []) if isinstance(ch, dict))

    ids: list = []
    for order in orders:
        if not isinstance(order, dict) or not references(order):
            continue
        status = str(order.get("status", "")).upper()
        cancelable = order.get("cancelable", status not in _TERMINAL_ORDER_STATUSES)
        oid = order.get("orderId")
        if cancelable and oid is not None:
            ids.append(oid)
    return list(dict.fromkeys(ids))


def _resting_close_order_ids(orders: list, symbols) -> list:
    """Outermost still-cancelable order ids that hold a resting CLOSING leg on any of `symbols`.

    Live-discovers the bracket however it was created — a separately-sent OCO (top level) OR an OTOCO
    entry's child OCO (nested under a filled entry) — so a close never races a bracket a stored id
    missed (the oversold-reject cause). Returns the cancelable order CLOSEST to the root in each
    branch (cancelling it cancels its children)."""
    wanted = {str(s or "").replace(" ", "") for s in symbols if s}
    closing = {"SELL_TO_CLOSE", "BUY_TO_CLOSE"}

    def references_close(order: dict) -> bool:
        for leg in (order.get("orderLegCollection") or []):
            sym = str((leg.get("instrument") or {}).get("symbol", "")).replace(" ", "")
            if sym in wanted and str(leg.get("instruction", "")).upper() in closing:
                return True
        return any(references_close(c) for c in (order.get("childOrderStrategies") or []) if isinstance(c, dict))

    found: list = []

    def walk(order) -> None:
        if not isinstance(order, dict):
            return
        status = str(order.get("status", "")).upper()
        cancelable = order.get("cancelable", status not in _TERMINAL_ORDER_STATUSES)
        oid = order.get("orderId")
        if cancelable and oid is not None and references_close(order):
            found.append(oid)
            return  # cancelling this cancels its children -- don't descend further
        for child in (order.get("childOrderStrategies") or []):
            walk(child)

    for order in orders:
        walk(order)
    return list(dict.fromkeys(found))


def _confirm_orders_cleared(
    order_client, account_hash, order_ids, frm, to, *, timeout_s: float = 2.0, step_s: float = 0.3
) -> bool:
    """Poll the order book until none of `order_ids` are still working (or `timeout_s` elapses).

    Lets a MARKET close wait for a just-cancelled bracket to actually leave the book, so Schwab can't
    see two sells against one contract ('oversold' reject). Returns True once all are cleared. Bounded;
    uses time.monotonic. Runs in a worker thread (the close path is asyncio.to_thread'd)."""
    if not order_ids:
        return True
    targets = {str(o) for o in order_ids}
    deadline = _time.monotonic() + max(timeout_s, 0.0)
    while True:
        try:
            orders = order_client.get_orders(account_hash, frm, to)
        except Exception:  # noqa: BLE001 -- can't read; let the close proceed rather than hang
            return False
        still_working: set = set()

        def scan(order):
            if not isinstance(order, dict):
                return
            oid = str(order.get("orderId") or "")
            if oid in targets and str(order.get("status", "")).upper() not in _TERMINAL_ORDER_STATUSES:
                still_working.add(oid)
            for child in (order.get("childOrderStrategies") or []):
                scan(child)

        for order in orders:
            scan(order)
        if not still_working:
            return True
        if _time.monotonic() >= deadline:
            return False
        _time.sleep(step_s)


def _target_prices_for_orders(orders: list) -> dict:
    """Map space-stripped OSI symbol -> price of a resting CLOSING limit order (the profit target).
    Skips stop legs and terminal orders; reads OCO/TRIGGER children. Powers the Target column."""
    closing = {"SELL_TO_CLOSE", "BUY_TO_CLOSE"}
    out: dict = {}

    def parse_price(value):
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    def scan(order):
        if not isinstance(order, dict):
            return
        status = str(order.get("status", "")).upper()
        otype = str(order.get("orderType", "")).upper()
        if status not in _TERMINAL_ORDER_STATUSES and otype in {"LIMIT", "NET_CREDIT", "NET_DEBIT"}:
            price = parse_price(order.get("price"))
            if price is not None:
                for leg in (order.get("orderLegCollection") or []):
                    if str(leg.get("instruction", "")).upper() in closing:
                        sym = str((leg.get("instrument") or {}).get("symbol", "")).replace(" ", "")
                        if sym:
                            out.setdefault(sym, price)
        for child in (order.get("childOrderStrategies") or []):
            scan(child)

    for order in orders:
        scan(order)
    return out


def _stop_prices_for_orders(orders: list) -> dict:
    """Map space-stripped OSI symbol -> the trigger of a resting CLOSING stop order (the OCO stop
    child). Mirror of _target_prices_for_orders but reads STOP `stopPrice`. Powers the Stop column."""
    closing = {"SELL_TO_CLOSE", "BUY_TO_CLOSE"}
    out: dict = {}

    def parse_price(value):
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    def scan(order):
        if not isinstance(order, dict):
            return
        status = str(order.get("status", "")).upper()
        otype = str(order.get("orderType", "")).upper()
        if status not in _TERMINAL_ORDER_STATUSES and otype in {"STOP", "STOP_LIMIT"}:
            price = parse_price(order.get("stopPrice"))
            if price is not None:
                for leg in (order.get("orderLegCollection") or []):
                    if str(leg.get("instruction", "")).upper() in closing:
                        sym = str((leg.get("instrument") or {}).get("symbol", "")).replace(" ", "")
                        if sym:
                            out.setdefault(sym, price)
        for child in (order.get("childOrderStrategies") or []):
            scan(child)

    for order in orders:
        scan(order)
    return out


def _load_spread_structure() -> dict:
    """Load the persisted per-account spread structure; {} on any problem so a bad file never blocks."""
    try:
        data = json.loads(_SPREAD_STRUCTURE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}


def _save_spread_structure() -> None:
    """Persist the spread structure (atomic temp+replace). Best-effort, never raises."""
    try:
        _SPREAD_STRUCTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SPREAD_STRUCTURE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(spread_structure, default=str), encoding="utf-8")
        os.replace(tmp, _SPREAD_STRUCTURE_PATH)
    except OSError:
        pass


spread_structure: dict = _load_spread_structure()


def _sync_spread_structure(client: SchwabMarketDataClient | None = None) -> dict:
    """Pull opening transactions per account (180-day) and reconstruct the per-order spread/single
    structure, MERGING onto the existing cache (a per-account failure keeps that account's prior
    reconstruction). Slow (transaction pulls) — runs on demand (Refresh) + on the P&L sync, not on
    every poll. Never raises."""
    global spread_structure
    accounts, _notes = discover_schwab_accounts(_bridge_config())
    eligible = [a for a in accounts if str(getattr(a, "account_hash", "") or "").strip()]
    if not eligible:
        return {"accounts": 0, "errors": ["no eligible accounts yet"]}
    client = client or SchwabMarketDataClient(settings.schwab)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=_SPREAD_STRUCTURE_LOOKBACK_DAYS)
    merged: dict = dict(spread_structure)
    errors: list[str] = []
    updated = 0
    for account in eligible:
        try:
            transactions = client.get_transactions(account.account_hash, start, now)
        except (SchwabApiError, SchwabOAuthError) as exc:
            errors.append(f"{getattr(account, 'id', '?')}: {str(exc)[:160]}")
            continue
        merged[account.id] = _reconstruct_orders_from_transactions(transactions)
        updated += 1
    spread_structure = merged
    _save_spread_structure()
    return {"accounts": updated, "errors": errors}


def _tracked_broker_symbols() -> set[str]:
    """Space-stripped option symbols this dashboard sent this session (from active_positions)."""
    out: set[str] = set()
    for p in active_positions.values():
        for leg in p.get("legs", []):
            sym = str(leg.get("broker_symbol", "")).replace(" ", "")
            if sym:
                out.add(sym)
    return out


def _normalize_option_position(account_id: str, raw: dict) -> dict | None:
    """Raw Schwab position -> normalized dict for the spread pipeline (None for non-option/flat)."""
    inst = raw.get("instrument") if isinstance(raw.get("instrument"), dict) else {}
    if str((inst or {}).get("assetType", "")) != "OPTION":
        return None
    net = _pos_float(raw.get("longQuantity")) - _pos_float(raw.get("shortQuantity"))
    if abs(net) < 1e-9:
        return None
    avg, mark, upnl = _position_avg_mark_pnl(raw)
    broker_symbol = str((inst or {}).get("symbol", "") or "")
    parsed = _parse_broker_option_symbol(broker_symbol)
    underlying = parsed[0] if parsed else str((inst or {}).get("underlyingSymbol", "") or "")
    return {
        "account_id": account_id,
        "symbol": broker_symbol,
        "underlying": underlying,
        "asset_type": "OPTION",
        "quantity": net,
        "average_price": avg,
        "mark": mark,
        "market_value": _pos_float(raw.get("marketValue")),
        "unrealized_pnl": upnl,
    }


def _positionrow_from_dict(d: dict, tracked_syms: set[str]) -> PositionRow:
    """Normalized position dict -> PositionRow (carries Target + spread flags for the panel)."""
    sym = str(d.get("symbol", "") or "")
    is_leg = bool(d.get("is_spread_leg"))
    qty = float(d.get("quantity") or 0)
    upnl = d.get("unrealized_pnl")
    return PositionRow(
        account_id=d["account_id"],
        account_label=_account_alias(d["account_id"]),
        symbol=sym,
        underlying=d.get("underlying", ""),
        qty=qty,
        avg=d.get("average_price"),
        mark=d.get("mark"),
        unrealized_pnl=(round(float(upnl), 2) if upnl is not None else None),
        direction="long" if qty > 0 else "short",
        closeable=(not is_leg and qty != 0),
        is_spread=is_leg,
        source="schwab",
        target_price=d.get("target_price"),
        stop_price=d.get("stop_price"),
        spread_id=d.get("spread_id"),
        is_spread_leg=is_leg,
        spread_aggregated=bool(d.get("spread_aggregated")),
        spread_kind=str(d.get("spread_kind") or ""),
        tracked=(sym.replace(" ", "") in tracked_syms),
    )


def _all_positions_response(client: SchwabMarketDataClient, *, fresh: bool = False) -> PositionsResponse:
    """Authoritative view: every OPTION position across enabled accounts. Applies the order#-based
    spread reconstruction (so a shared strike splits into its real spreads/singles), pairs remaining
    verticals, and attaches the resting closing-LIMIT Target price per symbol."""
    if fresh or not spread_structure:
        try:
            _sync_spread_structure(client)
        except Exception:  # noqa: BLE001 -- structure is an enhancement; never fail the panel
            pass
    accounts, _notes = discover_schwab_accounts(_bridge_config())
    enabled = [a for a in accounts if getattr(a, "enabled", False) and str(getattr(a, "account_hash", "") or "")]
    errors: list[str] = []
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    dicts_all: list[dict] = []
    for account in enabled:
        try:
            raws = client.get_positions(account.account_hash)
        except (SchwabApiError, SchwabOAuthError) as exc:
            errors.append(f"{getattr(account, 'id', '?')}: {str(exc)[:160]}")
            continue
        dicts = [d for raw in raws if (d := _normalize_option_position(account.id, raw))]
        if not dicts:
            continue
        structure = spread_structure.get(account.id)
        if structure:
            dicts = _apply_spread_structure(dicts, structure)
        _mark_spread_legs(dicts)
        targets: dict = {}
        stops: dict = {}
        try:
            acct_orders = client.get_orders(account.account_hash, frm, to)
            targets = _target_prices_for_orders(acct_orders)
            stops = _stop_prices_for_orders(acct_orders)
        except (SchwabApiError, SchwabOAuthError):
            pass
        for d in dicts:
            key = str(d.get("symbol") or "").replace(" ", "")
            d["target_price"] = targets.get(key)
            d["stop_price"] = stops.get(key)
        dicts_all.extend(dicts)
    tracked = _tracked_broker_symbols()
    rows = [_positionrow_from_dict(d, tracked) for d in dicts_all]
    rows.sort(key=lambda r: (r.account_label, r.symbol))
    return PositionsResponse(
        generated_at=now.replace(microsecond=0).isoformat(),
        mode="all",
        positions=rows,
        note="Live from Schwab · options · all enabled accounts.",
        errors=errors,
    )


def _tracked_positions_response(client: SchwabMarketDataClient | None = None) -> PositionsResponse:
    """One row per (account, symbol) the dashboard sent this session, enriched with live AVG/MARK/
    unrealized P&L from Schwab. get_positions cached per account_hash. Multi-leg -> spread (view-only)."""
    cache: dict[str, list] = {}

    def account_positions(account_hash: str) -> list:
        if account_hash not in cache:
            try:
                cache[account_hash] = client.get_positions(account_hash) if (client and account_hash) else []
            except Exception:  # noqa: BLE001 -- enrichment is best-effort
                cache[account_hash] = []
        return cache[account_hash]

    orders_cache: dict[str, tuple[dict, dict]] = {}  # hash -> (targets, stops)
    _now = datetime.now(timezone.utc)
    _frm = (_now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    _to = _now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def account_targets_stops(account_hash: str) -> tuple[dict, dict]:
        if account_hash not in orders_cache:
            try:
                od = client.get_orders(account_hash, _frm, _to) if (client and account_hash) else []
                orders_cache[account_hash] = (_target_prices_for_orders(od), _stop_prices_for_orders(od))
            except Exception:  # noqa: BLE001 -- Target/Stop are a nicety, never fail the panel
                orders_cache[account_hash] = ({}, {})
        return orders_cache[account_hash]

    rows: list[PositionRow] = []
    for p in active_positions.values():
        leg_syms = {str(leg.get("broker_symbol", "")).replace(" ", "") for leg in p.get("legs", [])}
        is_spread = len(p.get("legs", [])) > 1
        primary = p["legs"][0] if p.get("legs") else {}
        for aid in p.get("account_ids", []):
            account_hash = str(p.get("account_hashes", {}).get(aid, "") or "")
            avg = mark = upnl = None
            if client and account_hash:
                tot_upnl = 0.0
                tot_mv = 0.0
                net_q = 0.0
                matched = False
                for raw in account_positions(account_hash):
                    inst = raw.get("instrument") if isinstance(raw.get("instrument"), dict) else {}
                    if str((inst or {}).get("symbol", "")).replace(" ", "") in leg_syms:
                        matched = True
                        leg_avg, _leg_mark, leg_upnl = _position_avg_mark_pnl(raw)
                        tot_upnl += leg_upnl or 0.0
                        tot_mv += _pos_float(raw.get("marketValue"))
                        net_q += _pos_float(raw.get("longQuantity")) - _pos_float(raw.get("shortQuantity"))
                        if avg is None:
                            avg = leg_avg
                if matched:
                    upnl = round(tot_upnl, 2)
                    mark = round(tot_mv / (net_q * 100), 2) if net_q else None
            qty = float(primary.get("qty", 0) or 0)
            if p.get("direction") == "short":
                qty = -qty
            primary_sym = str(primary.get("broker_symbol", "") or "")
            target_price = stop_price = None
            if client and account_hash:
                targets, stops = account_targets_stops(account_hash)
                key = primary_sym.replace(" ", "")
                target_price = targets.get(key)
                stop_price = stops.get(key)
            rows.append(
                PositionRow(
                    account_id=aid,
                    account_label=_account_alias(aid),
                    symbol=primary_sym,
                    underlying=p.get("symbol", ""),
                    qty=qty,
                    avg=avg,
                    mark=mark,
                    unrealized_pnl=upnl,
                    direction=p.get("direction", ""),
                    closeable=(not is_spread),
                    is_spread=is_spread,
                    source="tracked",
                    sent_at=p.get("sent_at", ""),
                    target_price=target_price,
                    stop_price=stop_price,
                )
            )
    return PositionsResponse(
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        mode="tracked",
        positions=rows,
        note="Dashboard-tracked live sends; saved to disk and restored across restarts.",
    )


def _drop_tracked_contract(account_id: str, broker_symbol: str) -> None:
    """After a contract closes, drop that account from any tracked position holding it."""
    target = broker_symbol.replace(" ", "")
    changed = False
    for sym, p in list(active_positions.items()):
        leg_syms = {str(leg.get("broker_symbol", "")).replace(" ", "") for leg in p.get("legs", [])}
        if target in leg_syms and account_id in p.get("account_ids", []):
            p["account_ids"] = [a for a in p["account_ids"] if a != account_id]
            p["account_hashes"] = {k: v for k, v in p.get("account_hashes", {}).items() if k in p["account_ids"]}
            if not p["account_ids"]:
                active_positions.pop(sym, None)
            changed = True
    if changed:
        _save_active_positions()


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


def _close_contract_response(req: CloseContractRequest, order_client: SchwabMarketDataClient) -> ClosePositionResponse:
    """Close ONE option contract in one account via a MARKET order (cancel resting orders first).
    Works for both the tracked and the full-Schwab views. Triple-lock + confirm gated."""
    accounts, _notes = discover_schwab_accounts(_bridge_config())
    account = next((a for a in accounts if a.id == req.account_id), None)
    account_hash = str(getattr(account, "account_hash", "") or "").strip()
    label = _account_alias(req.account_id)
    live_gate_open = settings.service.live_gate_open
    payload = {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "MARKET",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "SELL_TO_CLOSE" if req.is_long else "BUY_TO_CLOSE",
                "quantity": req.qty,
                "instrument": {"symbol": req.broker_symbol, "assetType": "OPTION"},
            }
        ],
    }
    reasons: list[str] = []
    if not account_hash:
        reasons.append("account_hash_missing")
    if not live_gate_open:
        reasons.append("live_orders_blocked")
    elif not req.confirm_live_order:
        reasons.append("live_order_confirmation_required")
    hard_block = "account_hash_missing" in reasons

    if hard_block or not (live_gate_open and req.confirm_live_order):
        result = ClosePositionResult(
            account_id=req.account_id,
            account_label=label,
            status="dry_run" if (not hard_block and "live_orders_blocked" in reasons) else "blocked",
            reasons=list(dict.fromkeys(reasons or ["close_payload_ready"])),
            order_payload=payload,
        )
        return ClosePositionResponse(status=result.status, symbol=req.broker_symbol, account_results=[result], notes=[])

    # SAFE CLOSE: re-read authoritative state and BLOCK closing one leg of a vertical (flattening
    # a single leg would leave a naked option). Best-effort — if the re-read fails, fall through.
    try:
        live_dicts = [
            d for raw in order_client.get_positions(account_hash)
            if (d := _normalize_option_position(req.account_id, raw))
        ]
        _mark_spread_legs(live_dicts)
        compact = req.broker_symbol.replace(" ", "")
        match = next((d for d in live_dicts if str(d.get("symbol") or "").replace(" ", "") == compact), None)
        if match and match.get("is_spread_leg"):
            result = ClosePositionResult(
                account_id=req.account_id,
                account_label=label,
                status="blocked",
                reasons=["spread_leg_close_blocked"],
                order_payload=payload,
            )
            return ClosePositionResponse(
                status="blocked",
                symbol=req.broker_symbol,
                account_results=[result],
                notes=["This is one leg of a spread; closing it alone would leave a naked option. Close the whole structure in Schwab/thinkorswim."],
            )
    except Exception:  # noqa: BLE001 -- spread re-read is best-effort; fall through to the close
        pass

    # Cancel the resting bracket BEFORE flattening, then CONFIRM it left the book so the MARKET close
    # can't race a still-resting sell into a Schwab "oversold" reject (the DIA bug). Live-discover the
    # outermost cancelable closing order via get_orders (catches an OTOCO entry's nested child OCO and
    # replaced brackets that a stored id would miss); union the audit-derived ids as a fallback.
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    resting_ids: list = []
    try:
        resting_ids = _resting_close_order_ids(order_client.get_orders(account_hash, frm, to), [req.broker_symbol])
    except Exception:  # noqa: BLE001 -- fall back to the audit ids; the MARKET close still flattens it
        pass
    cancel_ids = list(dict.fromkeys(
        [str(i) for i in resting_ids] + list(_open_order_ids_for_symbol(req.account_id, req.broker_symbol))
    ))
    canceled: list[str] = []
    for order_id in cancel_ids:
        try:
            order_client.cancel_order(account_hash, str(order_id))
            canceled.append(str(order_id))
        except (SchwabApiError, SchwabOAuthError):
            pass  # best-effort; the confirm-poll + MARKET close still handle it
    # Wait (bounded) for the cancelled bracket to actually clear the book before the MARKET close.
    if resting_ids:
        _confirm_orders_cleared(order_client, account_hash, resting_ids, frm, to)
    try:
        placed = order_client.place_order(account_hash, payload)
        result = ClosePositionResult(
            account_id=req.account_id,
            account_label=label,
            status="submitted",
            reasons=["market_close_submitted"],
            broker_order_id=str(placed.get("broker_order_id") or "") or None,
            canceled_order_ids=canceled,
            order_payload=payload,
        )
        # Untrack ONLY on a clean close — a rejected close must keep the position tracked (visible +
        # retryable), never leave it naked and invisible.
        _drop_tracked_contract(req.account_id, req.broker_symbol)
    except (SchwabApiError, SchwabOAuthError) as exc:
        result = ClosePositionResult(
            account_id=req.account_id,
            account_label=label,
            status="blocked",
            reasons=[f"market_close_failed:{str(exc)[:200]}", "kept_tracked_retry_or_close_in_schwab"],
            canceled_order_ids=canceled,
            order_payload=payload,
        )
    note = (
        "Close failed — position kept tracked. Retry, or close it in Schwab/thinkorswim."
        if result.status == "blocked"
        else ""
    )
    return ClosePositionResponse(
        status=result.status,
        symbol=req.broker_symbol,
        account_results=[result],
        notes=[note] if note else [],
    )


@app.get("/positions", response_model=PositionsResponse)
async def positions(
    source: str = Query("tracked", pattern="^(tracked|all)$"),
    fresh: bool = Query(False),
) -> PositionsResponse:
    """Open positions. source=tracked -> only this dashboard's live sends this session;
    source=all -> every option position across enabled accounts (authoritative Schwab pull).
    fresh=true (Refresh button) rebuilds the slow order#-based spread structure on demand."""
    if source == "all":
        client = SchwabMarketDataClient(settings.schwab)
        return await asyncio.to_thread(_all_positions_response, client, fresh=fresh)
    client = SchwabMarketDataClient(settings.schwab) if active_positions else None
    return await asyncio.to_thread(_tracked_positions_response, client)


@app.post("/positions/close", response_model=ClosePositionResponse)
async def close_position(
    request: CloseContractRequest,
    _: None = Depends(_require_api_key),
) -> ClosePositionResponse:
    """Close a single option contract now: cancel resting orders + MARKET close. Triple-lock + confirm gated."""
    client = SchwabMarketDataClient(settings.schwab)
    response = await asyncio.to_thread(lambda: _close_contract_response(request, client))
    storage.append_order_event(
        {
            "event_type": "position_close",
            "account_id": request.account_id,
            "broker_symbol": request.broker_symbol,
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
    target_percentages: Annotated[
        str | None,
        Query(description="Comma-separated exit target percentages (OTOCO bracket sizing)."),
    ] = None,
    stop_loss_percent: Annotated[
        float,
        Query(ge=0, le=99, description="OTOCO protective stop, percent below entry limit. 0 disables the stop."),
    ] = float(DEFAULT_STOP_LOSS_PERCENT),
    stop_mode: Annotated[
        str,
        Query(description="Active stop management: fixed | breakeven | trailing | be_then_trail."),
    ] = "fixed",
    trail_start_percent: Annotated[
        float,
        Query(ge=0, le=100, description="Profit % at which stop management arms (single-leg OTOCO only)."),
    ] = 10.0,
    trail_distance_percent: Annotated[
        float,
        Query(ge=0, le=100, description="Trail distance as % of entry once armed."),
    ] = 8.0,
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
    # OTOCO ("1st Triggers OCO"): when the checkbox is on, place single-leg entries as N bracketed
    # slices so the target/stop are attached at the broker on fill. Verticals fall back to SINGLE.
    otoco_notes: list[str] = []
    otoco_payloads: list[dict] | None = None
    if request.otoco:
        entry_limit = (
            request.limit_price
            if request.limit_price is not None
            else proposal_to_send.send_limit_price
        )
        otoco_payloads = _schwab_otoco_entry_payloads(
            proposal_to_send,
            proposal_to_send.quantity,
            float(entry_limit or 0.0),
            _parse_target_percentages(target_percentages),
            stop_loss_percent,
        )
        if otoco_payloads:
            otoco_notes.append(
                f"OTOCO: entry placed as {len(otoco_payloads)} bracketed slice(s) "
                f"({'/'.join(str(p['quantity']) for p in otoco_payloads)}); each triggers an "
                f"OCO [target, stop] on fill."
            )
        else:
            otoco_notes.append(
                "OTOCO requested but not applied (verticals/no entry price are placed as a plain "
                "entry; send exits separately)."
            )
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
        payloads_to_place = otoco_payloads if otoco_payloads is not None else [order_payload]
        if live_gate_open and request.confirm_live_order:
            placed_ids: list[str | None] = []
            submit_error: str | None = None
            for payload in payloads_to_place:
                try:
                    placed = client.place_order(account.account_hash, payload)
                    placed_ids.append(str(placed.get("broker_order_id") or "") or None)
                except SchwabApiError as exc:
                    submit_error = str(exc)[:200]
                    break
            first_broker_id = next((bid for bid in placed_ids if bid), None)
            if submit_error is None:
                submit_reasons = (
                    [f"otoco_bracket_submitted:{len(placed_ids)}_slices"]
                    if otoco_payloads is not None
                    else ["schwab_order_submitted"]
                )
                results.append(
                    AccountSendResult(
                        account_id=account.id,
                        account_label=_account_display_label(account),
                        status="submitted",
                        reasons=submit_reasons,
                        broker_order_id=first_broker_id,
                        order_payload=payloads_to_place[0],
                    )
                )
            else:
                fail_reasons = [f"schwab_order_submit_failed:{submit_error}"]
                if placed_ids:
                    fail_reasons.append(
                        f"otoco_partial_submitted:{len(placed_ids)}_of_{len(payloads_to_place)}_slices"
                    )
                results.append(
                    AccountSendResult(
                        account_id=account.id,
                        account_label=_account_display_label(account),
                        status="blocked",
                        reasons=fail_reasons,
                        broker_order_id=first_broker_id,
                        order_payload=payloads_to_place[0],
                    )
                )
        else:
            dry_reasons = list(reasons)
            if otoco_payloads is not None and not dry_reasons:
                dry_reasons = [f"otoco_payloads_ready:{len(payloads_to_place)}_slices"]
            results.append(
                AccountSendResult(
                    account_id=account.id,
                    account_label=_account_display_label(account),
                    status="dry_run" if "live_orders_blocked" in reasons else "blocked",
                    reasons=dry_reasons or ["order_payload_ready"],
                    order_payload=payloads_to_place[0],
                )
            )

    status = _aggregate_status(results)
    # Track live-submitted positions so they (and only they) appear for dashboard Close-now.
    submitted = {r.account_id: r.broker_order_id for r in results if r.status == "submitted"}
    if submitted:
        stop_mgmt = _registration_stop_mgmt(
            proposal_to_send,
            otoco_applied=bool(otoco_payloads),
            target_percentages=_parse_target_percentages(target_percentages),
            stop_mode=stop_mode,
            trail_start_percent=trail_start_percent,
            trail_distance_percent=trail_distance_percent,
            stop_loss_percent=stop_loss_percent,
        )
        _register_active_position(proposal_to_send, list(submitted.keys()), accounts_by_id, submitted, stop_mgmt=stop_mgmt)
        if stop_mgmt:
            otoco_notes.append(
                f"Active stop: {stop_mgmt['mode']} arms at +{stop_mgmt['start_pct']:g}% "
                f"(trail {stop_mgmt['trail_pct']:g}%); monitored server-side."
            )
    response = SendProposalResponse(
        status=status,
        proposal_id=proposal_id,
        selected_account_ids=selected_ids,
        account_results=results,
        notes=[
            _send_note(status),
            *otoco_notes,
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


@app.post("/proposals/{proposal_id}/exits/send-all", response_model=SendProposalResponse)
async def send_all_exit_targets(
    proposal_id: str,
    request: SendExitTargetRequest,
    _: None = Depends(_require_api_key),
    target_percentages: Annotated[str | None, Query(description="Comma-separated exit target percentages.")] = None,
    stop_loss_percent: Annotated[float, Query(ge=0, le=99)] = float(DEFAULT_STOP_LOSS_PERCENT),
) -> SendProposalResponse:
    """Submit ALL exit-target OCOs in one call off a SINGLE entry-status fetch — so a transient
    status blip can't split the exits (the bug that left targets 2/3 unsent). Idempotent: targets
    already submitted are skipped via _has_submitted_exit_order. Used by the auto-send-on-fill flow."""
    proposal = storage.find_proposal(proposal_id) or _proposal_from_order_audit(proposal_id)
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
    target_indices = sorted({t.target_index for acc in order_status.account_statuses for t in acc.exit_targets})
    if not target_indices:
        return SendProposalResponse(
            status="blocked",
            proposal_id=proposal.id,
            selected_account_ids=request.selected_account_ids,
            notes=["No filled entry / exit targets available to send yet.", *account_notes],
        )
    merged: list[AccountSendResult] = []
    notes: list[str] = []
    for target_index in target_indices:
        resp = _send_exit_target_response(
            proposal=proposal,
            target_index=target_index,
            request=request,
            accounts=accounts,
            account_notes=[],
            order_status=order_status,  # shared fetch across all targets
            order_client=client,
        )
        storage.append_order_event(_exit_response_audit_event(resp, proposal, target_index, order_status))
        for r in resp.account_results:
            merged.append(r.model_copy(update={"reasons": [f"target#{target_index + 1}", *r.reasons]}))
        notes.extend(resp.notes)
    return SendProposalResponse(
        status=_aggregate_status(merged) if merged else "blocked",
        proposal_id=proposal.id,
        selected_account_ids=request.selected_account_ids,
        account_results=merged,
        notes=notes,
    )


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


def _schwab_otoco_entry_payloads(
    proposal: OptionProposal,
    quantity: int,
    entry_limit_price: float,
    target_percentages: list[float],
    stop_loss_percent: float,
) -> list[dict] | None:
    """Build OTOCO ("1st Triggers OCO") entry payloads — one per target slice (e.g. 5/3/2).

    Each payload is a TRIGGER entry (BUY_TO_OPEN the slice qty at the entry limit) whose child is
    the OCO bracket [target LIMIT, stop STOP] for that slice. When the entry fills, Schwab activates
    the bracket — so the exits are broker-managed and can't be lost to a dashboard/server outage.

    Bracket prices are derived from the ENTRY LIMIT (the fill is unknown at send time), reusing the
    same _exit_target_previews math the manual exit path uses, so a 10-lot at 20/50/60% maps to
    5@+20% / 3@+50% / 2@+60% with a shared protective stop. Returns None for verticals / no legs /
    a non-positive limit (caller falls back to the plain SINGLE entry)."""
    if proposal.structure != "single" or not proposal.legs or entry_limit_price <= 0:
        return None
    previews = _exit_target_previews(
        proposal,
        entry_limit_price,
        float(quantity),
        target_percentages,
        stop_loss_percent=stop_loss_percent,
    )
    if not previews:
        return None
    payloads: list[dict] = []
    for preview in previews:
        if preview.stop_trigger_price and preview.stop_trigger_price > 0:
            child_strategy = _schwab_single_option_oco_exit_payload(proposal, preview)
        else:
            # No protective stop -> the trigger fires a single target LIMIT (OTO, not OTOCO).
            child_strategy = {
                "session": "NORMAL",
                "duration": "GOOD_TILL_CANCEL",
                "orderType": "LIMIT",
                "complexOrderStrategyType": "NONE",
                "quantity": preview.qty,
                "price": f"{preview.target_limit_price:.2f}",
                "orderStrategyType": "SINGLE",
                "orderLegCollection": _schwab_exit_order_legs(proposal, preview.qty),
            }
        entry_legs = [
            {
                "instruction": "BUY_TO_OPEN" if leg.action == "BUY" else "SELL_TO_OPEN",
                "quantity": preview.qty,
                "instrument": {
                    "symbol": leg.broker_symbol or fallback_broker_option_symbol(leg),
                    "assetType": "OPTION",
                },
            }
            for leg in proposal.legs
        ]
        payloads.append(
            {
                "session": "NORMAL",
                "duration": "DAY",
                "orderType": "LIMIT",
                "complexOrderStrategyType": "NONE",
                "quantity": preview.qty,
                "price": f"{entry_limit_price:.2f}",
                "orderStrategyType": "TRIGGER",
                "orderLegCollection": entry_legs,
                "childOrderStrategies": [child_strategy],
            }
        )
    return payloads


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


# Front-weighted exit sizing: take more contracts off at the nearer targets and ride a smaller
# runner to the last. Weights per target count (largest first). e.g. 10 over 3 -> 5/3/2.
_FRONT_WEIGHTS = {1: [1.0], 2: [0.6, 0.4], 3: [0.5, 0.3, 0.2]}


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
    count = len(percentages)
    weights = _FRONT_WEIGHTS.get(count, [1.0 / count] * count)
    # Largest-remainder split so the quantities sum exactly to filled_contracts.
    raw = [filled_contracts * w for w in weights]
    qtys = [int(x) for x in raw]
    leftover = filled_contracts - sum(qtys)
    # Hand out leftover contracts by largest fractional part; ties go to the earlier target.
    order = sorted(range(count), key=lambda i: (-(raw[i] - qtys[i]), i))
    for k in range(leftover):
        qtys[order[k % count]] += 1
    # Guarantee front-loading: nearest target gets the most (T1 >= T2 >= T3).
    qtys.sort(reverse=True)
    return [(index, qty, percent) for index, (qty, percent) in enumerate(zip(qtys, percentages)) if qty > 0]


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
