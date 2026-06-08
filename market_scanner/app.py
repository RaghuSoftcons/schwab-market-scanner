from __future__ import annotations

import asyncio
import math
import re
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from nt_schwab_bridge.config import BridgeConfig, RiskConfig, ServiceConfig
from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg
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
    ProposalExitTargetPreview,
    ProposalOrderFillAccountStatus,
    ProposalOrderStatusResponse,
    ScanResult,
    SendProposalRequest,
    SendProposalResponse,
)
from market_scanner.orders import schwab_order_payload
from market_scanner.scanner import MarketScanner, ProposalBuildSettings
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
) -> list[ProposalExitTargetPreview]:
    if average_fill_price is None or filled_quantity <= 0:
        return []
    filled_contracts = max(0, int(math.floor(filled_quantity)))
    if filled_contracts <= 0:
        return []
    allocations = _exit_target_allocations(proposal, filled_contracts, target_percentages)
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
                estimated_profit=estimated_profit,
                tos_exit_order_line=_tos_exit_order_line_for_proposal(proposal, quantity, target_price),
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
