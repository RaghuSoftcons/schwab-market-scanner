from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from nt_schwab_bridge.config import BridgeConfig, RiskConfig, ServiceConfig
from nt_schwab_bridge.schwab_adapter import (
    SchwabApiError,
    SchwabMarketDataClient,
    discover_schwab_accounts,
    schwab_market_data_status,
)

from market_scanner.config import AppSettings, load_settings
from market_scanner.dashboard import dashboard_html
from market_scanner.models import AccountSendResult, ScanResult, SendProposalRequest, SendProposalResponse
from market_scanner.orders import schwab_order_payload
from market_scanner.scanner import MarketScanner
from market_scanner.storage import ScannerStorage


settings_load = load_settings()
settings: AppSettings = settings_load.settings
storage = ScannerStorage(settings.storage.path)
scanner = MarketScanner(settings)
_scheduler_task: asyncio.Task | None = None

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
    return dashboard_html()


@app.get("/schwab/status")
async def schwab_status() -> dict:
    return schwab_market_data_status(_bridge_config()).model_dump(mode="json")


@app.get("/accounts")
async def accounts(_: None = Depends(_require_api_key)) -> dict:
    discovered, notes = discover_schwab_accounts(_bridge_config())
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
            }
            for account in discovered
        ],
        "notes": notes,
    }


@app.post("/scan/run", response_model=ScanResult)
async def run_scan(
    _: None = Depends(_require_api_key),
    include_options: bool = True,
) -> ScanResult:
    result = await asyncio.to_thread(scanner.scan, include_options=include_options)
    _rank_candidates(result)
    storage.save_scan(result)
    return result


@app.post("/scan/selected/{symbol}", response_model=ScanResult)
async def build_selected_scan_proposals(
    symbol: str,
    _: None = Depends(_require_api_key),
) -> ScanResult:
    normalized = symbol.upper().replace("$", "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Symbol is required.")
    result = storage.load_latest_scan()
    if result is None:
        result = await asyncio.to_thread(scanner.scan, include_options=False)
        _rank_candidates(result)
    try:
        result = await asyncio.to_thread(scanner.build_selected_candidate_proposals, result, normalized)
    except ValueError:
        result = await asyncio.to_thread(scanner.scan, include_options=False)
        _rank_candidates(result)
        try:
            result = await asyncio.to_thread(scanner.build_selected_candidate_proposals, result, normalized)
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
        storage.append_order_event(response.model_dump(mode="json"))
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
        storage.append_order_event(response.model_dump(mode="json"))
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
    storage.append_order_event(response.model_dump(mode="json"))
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
