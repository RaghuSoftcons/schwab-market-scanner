"""Read-only Schwab market-data adapter for dry-run proposal generation.

Port Change Log (Scanner <- Unified Platform):
- 2026-06-22 14:11 EST | Phase 1 | Replaced flat available-funds priority list with the
  account-type-aware selection + _conservative_available() helper (MARGIN -> availableFunds,
  CASH -> cashAvailableForTrading, min(current, projected)). Fixes overstated availability.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, get_ident
from typing import Any

import httpx
from pydantic import ValidationError

from nt_schwab_bridge.config import BridgeConfig, OptionPlannerConfig, SchwabAccountConfig, SchwabConfig
from nt_schwab_bridge.models import (
    OptionContractSnapshot,
    OptionRight,
    SchwabMarketDataStatusResponse,
    SchwabOptionChainCheckResponse,
    SchwabOptionChainSample,
    SignalRecord,
)


LOGGER = logging.getLogger(__name__)
HttpClientFactory = Callable[[], httpx.Client]
_TOKEN_REFRESH_LOCK = Lock()
_CLEAN_PROJECT_DIR_NAME = "ChatGPT to Schwab Integration CLEAN"
_SHARED_CLIENT_ENV_VARS = ("SCHWAB_SHARED_CLIENT_ENV_PATH", "NT_SCHWAB_SHARED_CLIENT_ENV_PATH")
_PLACEHOLDER_SECRET_VALUES = {
    "your-schwab-client-id",
    "your-schwab-client-secret",
    "your-schwab-access-token",
    "your-schwab-refresh-token",
}


class SchwabConfigurationError(RuntimeError):
    """Raised when Schwab market data is enabled but not configured."""


class SchwabOAuthError(RuntimeError):
    """Raised when a usable Schwab access token is not available."""


class SchwabApiError(RuntimeError):
    """Raised when a read-only Schwab market-data request fails."""


def build_schwab_option_chain_provider(config: BridgeConfig) -> SchwabOptionChainProvider | None:
    """Build an opt-in read-only option-chain provider for app startup."""

    if not config.schwab.market_data_enabled:
        return None
    if not (config.schwab.token_authority_url or config.schwab.token_store_path or config.schwab.access_token or config.schwab.refresh_token):
        LOGGER.warning("Schwab market data is enabled, but no token source is configured.")
        return None
    return SchwabOptionChainProvider(
        client=SchwabMarketDataClient(config.schwab),
        planner_config=config.options,
    )


def schwab_market_data_status(config: BridgeConfig) -> SchwabMarketDataStatusResponse:
    """Return local read-only Schwab readiness without making market-data calls."""

    schwab = config.schwab
    token_source_configured = bool(schwab.token_authority_url or schwab.token_store_path or schwab.access_token or schwab.refresh_token)
    base_payload = {
        "enabled": schwab.market_data_enabled,
        "auto_refresh_enabled": schwab.auto_refresh_enabled,
        "provider_configured": token_source_configured,
        "api_base_configured": bool(schwab.api_base_url),
        "token_store_configured": bool(schwab.token_store_path),
        "token_authority_configured": bool(schwab.token_authority_url and schwab.token_authority_api_key),
        "client_id_configured": bool(schwab.client_id),
        "client_secret_configured": bool(schwab.client_secret),
        "account_hash_configured": bool(schwab.account_hash),
    }

    if not schwab.market_data_enabled:
        return SchwabMarketDataStatusResponse(
            status="disabled",
            read_only_ready=False,
            access_token_present=False,
            refresh_token_present=False,
            needs_refresh=False,
            notes=["Schwab market data is disabled in config."],
            **base_payload,
        )
    if not token_source_configured:
        return SchwabMarketDataStatusResponse(
            status="not_configured",
            read_only_ready=False,
            access_token_present=False,
            refresh_token_present=False,
            needs_refresh=False,
            notes=["No Schwab token source is configured."],
            **base_payload,
        )

    try:
        oauth_status = SchwabOAuthManager(schwab).status()
    except SchwabOAuthError as exc:
        return SchwabMarketDataStatusResponse(
            status="config_error",
            read_only_ready=False,
            access_token_present=False,
            refresh_token_present=False,
            needs_refresh=False,
            notes=["Schwab token status could not be read."],
            error=f"{exc.__class__.__name__}: {exc}",
            **base_payload,
        )

    base_payload["client_id_configured"] = bool(oauth_status.get("client_id_configured"))
    base_payload["client_secret_configured"] = bool(oauth_status.get("client_secret_configured"))
    access_token_present = bool(oauth_status.get("has_access_token"))
    refresh_token_present = bool(oauth_status.get("has_refresh_token"))
    needs_refresh = bool(oauth_status.get("needs_refresh"))
    can_refresh = refresh_token_present and bool(
        oauth_status.get("client_id_configured") and oauth_status.get("client_secret_configured")
    )
    bridge_can_refresh = can_refresh and schwab.auto_refresh_enabled

    notes: list[str] = []
    if access_token_present and not needs_refresh:
        status = "auth_ready"
        read_only_ready = True
        notes.append("Access token is present for read-only market-data calls.")
    elif bridge_can_refresh:
        status = "refresh_ready"
        read_only_ready = True
        notes.append("Refresh token and client credentials are present; access token can be refreshed on demand.")
    else:
        status = "auth_required"
        read_only_ready = False
        if needs_refresh:
            notes.append("Access token is expired or near expiry.")
            if can_refresh and not schwab.auto_refresh_enabled:
                notes.append("Use the shared Schwab auth/refresh flow; this bridge will not refresh tokens.")
        if refresh_token_present and not can_refresh:
            notes.append("Refresh token is present, but client credentials are required to refresh it.")
        if not access_token_present and not refresh_token_present:
            notes.append("No usable Schwab token is present.")

    execution_ready = read_only_ready and _schwab_live_order_gate_open(config)
    notes.append(_schwab_order_status_note(config, read_only_ready=read_only_ready))
    return SchwabMarketDataStatusResponse(
        status=status,
        read_only_ready=read_only_ready,
        execution_ready=execution_ready,
        access_token_present=access_token_present,
        refresh_token_present=refresh_token_present,
        access_token_expires_at=oauth_status.get("access_token_expires_at"),
        needs_refresh=needs_refresh,
        notes=notes,
        **base_payload,
    )


def schwab_option_chain_check(
    config: BridgeConfig,
    symbol: str = "SPY",
    direction: str = "long",
    expiry_label: str = "1DTE",
    client: SchwabMarketDataClient | None = None,
    as_of: date | None = None,
) -> SchwabOptionChainCheckResponse:
    """Make one read-only Schwab option-chain check and return a safe summary."""

    normalized_symbol = _normalize_symbol(symbol)
    status = schwab_market_data_status(config)
    right = _right_for_direction(direction)
    expiry = _resolve_expiry_label(expiry_label, as_of or datetime.now(timezone.utc).date())
    base_payload = {
        "symbol": normalized_symbol,
        "expiry": expiry,
        "contract_type": right,
        "read_only_ready": status.read_only_ready,
    }
    if not config.schwab.market_data_enabled:
        return SchwabOptionChainCheckResponse(
            status="disabled",
            notes=["Schwab market data is disabled in config."],
            **base_payload,
        )
    if not status.provider_configured:
        return SchwabOptionChainCheckResponse(
            status="not_configured",
            notes=["No Schwab token source is configured."],
            **base_payload,
        )
    if expiry is None:
        return SchwabOptionChainCheckResponse(
            status="error",
            error=f"Invalid expiry label: {expiry_label}",
            **base_payload,
        )

    data_client = client or SchwabMarketDataClient(config.schwab)
    try:
        contracts = data_client.get_option_chain(normalized_symbol, expiry, contract_type=right)
    except (SchwabApiError, SchwabOAuthError) as exc:
        error = str(exc)
        return SchwabOptionChainCheckResponse(
            status="auth_required" if _is_auth_required_error(error) else "error",
            error=error,
            request_meta=dict(getattr(data_client, "last_option_chain_request_params", {})),
            notes=[_schwab_chain_check_note(config, status.read_only_ready)],
            **base_payload,
        )

    request_meta = dict(getattr(data_client, "last_option_chain_request_params", {}))
    underlying_price = _optional_nonnegative_float(request_meta.get("underlying_price"))
    return SchwabOptionChainCheckResponse(
        status="received",
        contract_count=len(contracts),
        underlying_price=underlying_price,
        sample=[
            SchwabOptionChainSample(
                expiry=contract.expiry,
                strike=contract.strike,
                right=contract.right,
                bid=contract.bid,
                ask=contract.ask,
                delta=contract.delta,
                open_interest=contract.open_interest,
                volume=contract.volume,
                quote_time=contract.timestamp,
            )
            for contract in _chain_check_sample(contracts, right=right, underlying_price=underlying_price)
        ],
        request_meta=request_meta,
        notes=[_schwab_chain_check_note(config, status.read_only_ready)],
        **base_payload,
    )


def discover_schwab_accounts(
    config: BridgeConfig,
    client: SchwabMarketDataClient | None = None,
) -> tuple[list[SchwabAccountConfig], list[str]]:
    """Discover Schwab account hashes with masked labels for local routing only."""

    schwab = config.schwab
    if not schwab.account_discovery_enabled:
        return [], ["Schwab account discovery is disabled."]
    if not schwab.market_data_enabled:
        return [], ["Schwab account discovery requires Schwab API access to be enabled."]
    if not (schwab.token_authority_url or schwab.token_store_path or schwab.access_token or schwab.refresh_token):
        return [], ["No Schwab token source is configured for account discovery."]

    data_client = client or SchwabMarketDataClient(schwab)
    configured_by_hash = {
        account.account_hash: account
        for account in schwab.accounts
        if account.account_hash and account.enabled
    }
    configured_by_number = {
        account.account_number: account
        for account in schwab.accounts
        if account.account_number and account.enabled
    }
    configured_by_id = {account.id: account for account in schwab.accounts if account.enabled}
    notes: list[str] = []
    try:
        discovered = data_client.list_accounts()
    except (SchwabApiError, SchwabOAuthError) as exc:
        return [], [f"Schwab account discovery failed: {exc}"]

    accounts: list[SchwabAccountConfig] = []
    for item in discovered:
        account_hash = str(item.get("account_hash", "") or "").strip()
        if not account_hash:
            continue
        account_number = str(item.get("account_number", "") or "").strip()
        masked = str(item.get("account_number_masked", "") or "unknown")
        account_id = _account_id_from_number(account_number) if account_number else _account_id_from_hash(account_hash)
        configured = configured_by_hash.get(account_hash) or configured_by_number.get(account_number) or configured_by_id.get(account_id)
        account_type = configured.account_type if configured else "unknown"
        if account_type == "unknown":
            try:
                account_type = data_client.get_account_type(account_hash)
            except (SchwabApiError, SchwabOAuthError) as exc:
                notes.append(f"Could not read account type for {masked}: {exc}")
        if configured and configured.supports_spreads:
            supports_spreads = True
        elif configured and configured.account_type == "cash":
            supports_spreads = False
        else:
            supports_spreads = account_type == "margin"
        accounts.append(
            SchwabAccountConfig(
                id=configured.id if configured else account_id,
                label=configured.label if configured and configured.label else f"Schwab {masked}",
                account_number=account_number or (configured.account_number if configured else ""),
                account_hash=account_hash,
                source="discovered",
                account_type=account_type,
                supports_spreads=supports_spreads,
                enabled=configured.enabled if configured else True,
                default_selected=configured.default_selected if configured else True,
            )
        )

    if accounts:
        notes.append(f"Discovered {len(accounts)} Schwab account(s) from the shared token.")
    return accounts, notes


class SchwabOAuthManager:
    """Small token manager for read-only Schwab market-data calls."""

    def __init__(self, config: SchwabConfig, http_client_factory: HttpClientFactory | None = None) -> None:
        self.config = config
        self.token_store_path = Path(config.token_store_path).expanduser() if config.token_store_path else None
        self.refresh_skew = timedelta(seconds=config.token_refresh_skew_seconds)
        self._http_client_factory = http_client_factory or (
            lambda: httpx.Client(timeout=config.timeout_seconds, trust_env=False)
        )
        self._client_credentials: tuple[str, str] | None = None
        self._authority_token_state: dict[str, Any] | None = None
        self._authority_token_fetched_at: datetime | None = None

    def get_access_token(self) -> str:
        authority_error: SchwabOAuthError | None = None
        if self._token_authority_configured():
            try:
                authority_state = self.fetch_authority_token_state()
                authority_token = str(authority_state.get("access_token", "") or "")
                if authority_token and not self.is_access_token_expiring(authority_state):
                    return authority_token
            except SchwabOAuthError as exc:
                authority_error = exc
                LOGGER.warning("Schwab token authority fetch failed: %s", exc)

        state = self.load_token_state()
        access_token = str(state.get("access_token", "") or "")
        if access_token and not self.is_access_token_expiring(state):
            return access_token
        if state.get("refresh_token") and self.config.auto_refresh_enabled:
            refreshed = self.refresh_access_token(state)
            token = str(refreshed.get("access_token", "") or "")
            if token:
                return token
        if access_token:
            raise SchwabOAuthError(
                "Schwab access token is expired or expiring. Use the shared Schwab auth/refresh flow."
            )
        if authority_error is not None:
            raise authority_error
        raise SchwabOAuthError("No Schwab access token is available. Login is required.")

    def _token_authority_configured(self) -> bool:
        return bool(str(self.config.token_authority_url or "").strip() and str(self.config.token_authority_api_key or "").strip())

    def fetch_authority_token_state(self) -> dict[str, Any]:
        cached = self._authority_token_state
        if cached and not self.is_access_token_expiring(cached):
            fetched_at = self._authority_token_fetched_at
            cache_seconds = int(self.config.token_authority_cache_seconds or 0)
            if cache_seconds <= 0 or (fetched_at and datetime.now(timezone.utc) - fetched_at < timedelta(seconds=cache_seconds)):
                return cached

        url = str(self.config.token_authority_url or "").strip()
        api_key = str(self.config.token_authority_api_key or "").strip()
        if not url or not api_key:
            raise SchwabOAuthError("Schwab token authority is not configured.")
        try:
            with self._http_client_factory() as client:
                response = client.get(url, headers={"Accept": "application/json", "X-API-Key": api_key})
        except Exception as exc:
            raise SchwabOAuthError(f"Schwab token authority request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SchwabOAuthError(f"Schwab token authority returned {response.status_code}: {response.text[:200]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SchwabOAuthError("Schwab token authority returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise SchwabOAuthError("Schwab token authority returned an unexpected payload shape.")
        access_token = str(payload.get("access_token", "") or "")
        if not access_token:
            raise SchwabOAuthError("Schwab token authority returned no access token.")
        state = {
            "access_token": access_token,
            "access_token_expires_at": payload.get("access_token_expires_at", ""),
            "token_type": payload.get("token_type", "Bearer") or "Bearer",
        }
        self._authority_token_state = state
        self._authority_token_fetched_at = datetime.now(timezone.utc)
        return state

    def load_token_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "access_token": self.config.access_token,
            "refresh_token": self.config.refresh_token,
            "access_token_expires_at": self.config.access_token_expires_at,
            "token_type": "Bearer",
        }
        if self.token_store_path is None:
            return {key: value for key, value in state.items() if value not in (None, "")}
        try:
            if self.token_store_path.exists() and self.token_store_path.is_file():
                persisted = json.loads(self.token_store_path.read_text(encoding="utf-8"))
                if isinstance(persisted, dict):
                    state.update({key: value for key, value in persisted.items() if value not in (None, "")})
        except OSError as exc:
            raise SchwabOAuthError(f"Unable to read Schwab token store: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise SchwabOAuthError(f"Unable to parse Schwab token store JSON: {exc}") from exc
        return {key: value for key, value in state.items() if value not in (None, "")}

    def save_token_state(self, state: dict[str, Any]) -> None:
        if self.token_store_path is None:
            return
        payload = dict(state)
        payload["saved_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        serialized = json.dumps(payload, indent=2)
        temp_path = self.token_store_path.with_name(
            f"{self.token_store_path.name}.{os.getpid()}.{get_ident()}.tmp"
        )
        try:
            self.token_store_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(serialized, encoding="utf-8")
            temp_path.replace(self.token_store_path)
        except OSError as exc:
            raise SchwabOAuthError(f"Unable to write Schwab token store: {exc}") from exc
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass

    def is_access_token_expiring(self, state: dict[str, Any]) -> bool:
        expires_at = _parse_datetime(state.get("access_token_expires_at"))
        if expires_at is None:
            return False
        return datetime.now(timezone.utc) + self.refresh_skew >= expires_at

    def client_credentials(self) -> tuple[str, str]:
        if self._client_credentials is not None:
            return self._client_credentials
        client_id = str(self.config.client_id or "").strip()
        client_secret = str(self.config.client_secret or "").strip()
        if not (_is_usable_secret(client_id) and _is_usable_secret(client_secret)):
            client_id = ""
            client_secret = ""
        if self.config.import_existing_client and not (client_id and client_secret):
            imported_client_id, imported_client_secret = _import_existing_client_credentials()
            if imported_client_id and imported_client_secret:
                client_id = imported_client_id
                client_secret = imported_client_secret
        self._client_credentials = (client_id, client_secret)
        return self._client_credentials

    def refresh_access_token(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        with _TOKEN_REFRESH_LOCK:
            current_state = state or self.load_token_state()
            if self.token_store_path is not None:
                latest_state = self.load_token_state()
                if latest_state.get("access_token") and not self.is_access_token_expiring(latest_state):
                    return latest_state
                current_state = latest_state
            refresh_token = str(current_state.get("refresh_token", "") or "")
            if not refresh_token:
                current_state["login_required"] = True
                current_state["last_auth_error"] = "No Schwab refresh token is available. Login is required."
                self.save_token_state(current_state)
                raise SchwabOAuthError("No Schwab refresh token is available. Login is required.")
            client_id, client_secret = self.client_credentials()
            if not client_id or not client_secret:
                raise SchwabOAuthError(
                    "Schwab client credentials are required to refresh the access token."
                )

            try:
                with self._http_client_factory() as client:
                    response = client.post(
                        self.config.token_url,
                        auth=(client_id, client_secret),
                        data={
                            "grant_type": "refresh_token",
                            "refresh_token": refresh_token,
                        },
                        headers={"Accept": "application/json"},
                    )
            except Exception as exc:
                current_state["login_required"] = True
                current_state["last_auth_error"] = str(exc)
                self.save_token_state(current_state)
                raise SchwabOAuthError(f"Failed to refresh Schwab token: {exc}") from exc
            if response.status_code >= 400:
                current_state["login_required"] = True
                current_state["last_auth_error"] = f"refresh_failed:{response.status_code}"
                self.save_token_state(current_state)
                raise SchwabOAuthError(f"Failed to refresh Schwab token: {response.status_code} {response.text[:200]}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise SchwabOAuthError("Unexpected Schwab token-refresh payload shape.")
            updated = _merge_token_payload(current_state, payload)
            self.save_token_state(updated)
            return updated

    def status(self) -> dict[str, Any]:
        state = self.load_token_state()
        authority_error = None
        if self._token_authority_configured():
            try:
                state.update(self.fetch_authority_token_state())
            except SchwabOAuthError as exc:
                authority_error = str(exc)
        client_id, client_secret = self.client_credentials()
        expires_at = _parse_datetime(state.get("access_token_expires_at"))
        has_access_token = bool(state.get("access_token"))
        has_refresh_token = bool(state.get("refresh_token"))
        needs_refresh = self.is_access_token_expiring(state)
        return {
            "has_access_token": has_access_token,
            "has_refresh_token": has_refresh_token,
            "access_token_expires_at": expires_at,
            "needs_refresh": needs_refresh,
            "login_required": not has_access_token and not has_refresh_token,
            "token_store_path": str(self.token_store_path) if self.token_store_path else "",
            "token_authority_configured": self._token_authority_configured(),
            "token_authority_error": authority_error,
            "client_id_configured": bool(client_id),
            "client_secret_configured": bool(client_secret),
        }


class SchwabMarketDataClient:
    """Read-only Schwab market-data client for option-chain snapshots."""

    def __init__(
        self,
        config: SchwabConfig,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self.config = config
        self.base_url = config.api_base_url.rstrip("/")
        self.timeout = config.timeout_seconds
        self._http_client_factory = http_client_factory or (
            lambda: httpx.Client(timeout=self.timeout, trust_env=False)
        )
        self.oauth_manager = SchwabOAuthManager(config, http_client_factory=self._http_client_factory)
        self.last_option_chain_request_params: dict[str, Any] = {}

    def get_option_chain(
        self,
        symbol: str,
        expiration: date,
        contract_type: str = "ALL",
    ) -> list[OptionContractSnapshot]:
        path = "/marketdata/v1/chains"
        normalized_symbol = _normalize_symbol(symbol)
        normalized_type = contract_type.upper().strip()
        if normalized_type not in {"ALL", "CALL", "PUT"}:
            raise SchwabApiError(f"Unsupported Schwab option contract type: {contract_type}")

        primary_params = {
            "symbol": normalized_symbol,
            "contractType": normalized_type,
            "fromDate": expiration.isoformat(),
            "toDate": expiration.isoformat(),
        }
        fallback_params = {
            "symbol": normalized_symbol,
            "contractType": normalized_type,
            "range": "ALL",
            "strategy": "SINGLE",
        }
        self.last_option_chain_request_params = {
            "symbol": normalized_symbol,
            "requested_expiry": expiration.isoformat(),
            "contract_type": normalized_type,
            "request_params_primary": dict(primary_params),
            "request_params_fallback": None,
            "http_status_primary": None,
            "http_status_fallback": None,
            "fallback_recovered": False,
        }

        payload, status_code, response_text = self._get_json_with_status(path, params=primary_params)
        self.last_option_chain_request_params["http_status_primary"] = status_code
        if status_code >= 400:
            self.last_option_chain_request_params["request_params_fallback"] = dict(fallback_params)
            payload, fallback_status, fallback_text = self._get_json_with_status(path, params=fallback_params)
            self.last_option_chain_request_params["http_status_fallback"] = fallback_status
            if fallback_status >= 400:
                raise SchwabApiError(
                    f"Schwab API error for option chain: {fallback_status} {(fallback_text or response_text)[:200]}"
                )
            self.last_option_chain_request_params["fallback_recovered"] = True

        self.last_option_chain_request_params["underlying_price"] = _extract_underlying_price(payload)
        contracts: list[OptionContractSnapshot] = []
        if normalized_type in {"ALL", "CALL"}:
            contracts.extend(self._parse_chain_map(normalized_symbol, payload.get("callExpDateMap", {}), "CALL"))
        if normalized_type in {"ALL", "PUT"}:
            contracts.extend(self._parse_chain_map(normalized_symbol, payload.get("putExpDateMap", {}), "PUT"))
        return [contract for contract in contracts if contract.expiry == expiration]

    def list_accounts(self) -> list[dict[str, str]]:
        payload = self._get_any_json("/trader/v1/accounts/accountNumbers")
        if not isinstance(payload, list):
            raise SchwabApiError(f"Unexpected Schwab account discovery payload type: {type(payload).__name__}")
        accounts: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            account_number = str(item.get("accountNumber", "") or "")
            account_hash = str(item.get("hashValue", "") or item.get("accountHash", "") or "")
            if not account_hash:
                continue
            accounts.append(
                {
                    "account_number_masked": _mask_account_number(account_number),
                    "account_number": account_number,
                    "account_hash": account_hash,
                }
            )
        if not accounts:
            raise SchwabApiError("No Schwab account hashes were returned.")
        return accounts

    def get_account_type(self, account_hash: str) -> str:
        payload, status_code, response_text = self._get_json_with_status(f"/trader/v1/accounts/{account_hash}")
        if status_code >= 400:
            raise SchwabApiError(f"Schwab API error for account detail: {status_code} {response_text[:200]}")
        account = payload.get("securitiesAccount", payload)
        if not isinstance(account, dict):
            return "unknown"
        raw_type = str(account.get("type", "") or account.get("accountType", "") or "").upper()
        if "MARGIN" in raw_type:
            return "margin"
        if "CASH" in raw_type:
            return "cash"
        return "unknown"

    def get_account_balance_summary(self, account_hash: str) -> dict[str, Any]:
        """Read a minimal balance summary for dashboard routing hints."""

        if not account_hash.strip():
            raise SchwabApiError("Schwab account hash is required before reading account balances.")
        payload, status_code, response_text = self._get_json_with_status(f"/trader/v1/accounts/{account_hash}")
        if status_code >= 400:
            raise SchwabApiError(f"Schwab API error for account balances: {status_code} {response_text[:200]}")
        account = payload.get("securitiesAccount", payload)
        if not isinstance(account, dict):
            return {}
        return _extract_account_balance_summary(account)

    def place_order(self, account_hash: str, order_payload: dict[str, Any]) -> dict[str, Any]:
        if not account_hash.strip():
            raise SchwabApiError("Schwab account hash is required before placing an order.")
        url = f"{self.base_url}/trader/v1/accounts/{account_hash}/orders"
        try:
            with self._http_client_factory() as client:
                response = client.post(url, headers=self._headers(), json=order_payload)
        except Exception as exc:
            raise SchwabApiError(f"Schwab order placement request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SchwabApiError(f"Schwab order placement failed: {response.status_code} {response.text[:500]}")
        location = response.headers.get("Location", "")
        broker_order_id = _broker_order_id_from_location(location)
        payload: dict[str, Any] = {
            "status_code": response.status_code,
            "location": location,
            "broker_order_id": broker_order_id,
        }
        if response.text.strip():
            try:
                payload["response"] = response.json()
            except ValueError:
                payload["response_text"] = response.text[:500]
        return payload

    def get_order(self, account_hash: str, order_id: str) -> dict[str, Any]:
        if not account_hash.strip():
            raise SchwabApiError("Schwab account hash is required before reading an order.")
        if not order_id.strip():
            raise SchwabApiError("Schwab order id is required before reading an order.")
        payload, status_code, response_text = self._get_json_with_status(
            f"/trader/v1/accounts/{account_hash}/orders/{order_id}"
        )
        if status_code >= 400:
            raise SchwabApiError(f"Schwab order status request failed: {status_code} {response_text[:500]}")
        return payload

    def get_orders(
        self,
        account_hash: str,
        from_entered_time: str,
        to_entered_time: str,
        max_results: int = 300,
    ) -> list[dict[str, Any]]:
        """List orders for an account in a time window (returns a JSON list).

        Used for the Open Positions Target column (resting closing-LIMIT price) and the safe
        per-row Close (cancel ALL resting orders for a symbol before flattening)."""
        if not account_hash.strip():
            raise SchwabApiError("Schwab account hash is required before listing orders.")
        url = f"{self.base_url}/trader/v1/accounts/{account_hash}/orders"
        params = {
            "fromEnteredTime": from_entered_time,
            "toEnteredTime": to_entered_time,
            "maxResults": max_results,
        }
        try:
            with self._http_client_factory() as client:
                response = client.get(url, headers=self._headers(), params=params)
        except Exception as exc:
            raise SchwabApiError(f"Schwab order list request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SchwabApiError(f"Schwab order list failed: {response.status_code} {response.text[:500]}")
        data = response.json() if response.text.strip() else []
        return data if isinstance(data, list) else []

    def get_transactions(
        self, account_hash: str, start: datetime, end: datetime, types: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch executed transactions (the array endpoint) for realized-P&L sync.
        types=None fetches ALL types so option expirations/assignments
        (RECEIVE_AND_DELIVER) are included alongside TRADE."""
        if not account_hash.strip():
            raise SchwabApiError("Schwab account hash is required before reading transactions.")
        params = {
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "endDate": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        if types:
            params["types"] = types
        url = f"{self.base_url}/trader/v1/accounts/{account_hash}/transactions"
        try:
            with self._http_client_factory() as client:
                response = client.get(url, headers=self._headers(), params=params)
        except Exception as exc:
            raise SchwabApiError(f"Schwab transactions request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SchwabApiError(
                f"Schwab transactions request failed: {response.status_code} {response.text[:300]}"
            )
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("transactions", "data", "items"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []

    def get_positions(self, account_hash: str) -> list[dict[str, Any]]:
        """AUTHORITATIVE open-positions pull straight from Schwab.

        The scanner places trades directly across multiple accounts, so an in-memory
        tracker would miss directly-placed and post-restart positions. We always read
        broker truth via /accounts/{hash}?fields=positions. Returns the raw position
        dicts (each carries an `instrument`, `longQuantity`/`shortQuantity`,
        `averagePrice`, `marketValue`, etc.); aggregation/normalisation is the caller's job.
        """
        if not account_hash.strip():
            raise SchwabApiError("Schwab account hash is required before reading positions.")
        payload, status_code, response_text = self._get_json_with_status(
            f"/trader/v1/accounts/{account_hash}", params={"fields": "positions"}
        )
        if status_code >= 400:
            raise SchwabApiError(f"Schwab positions request failed: {status_code} {response_text[:300]}")
        account = payload.get("securitiesAccount") if isinstance(payload, dict) else None
        if not isinstance(account, dict):
            return []
        positions = account.get("positions")
        return positions if isinstance(positions, list) else []

    def cancel_order(self, account_hash: str, order_id: str) -> None:
        if not account_hash.strip():
            raise SchwabApiError("Schwab account hash is required before cancelling an order.")
        if not order_id.strip():
            raise SchwabApiError("Schwab order id is required before cancelling an order.")
        url = f"{self.base_url}/trader/v1/accounts/{account_hash}/orders/{order_id}"
        try:
            with self._http_client_factory() as client:
                response = client.delete(url, headers=self._headers())
        except Exception as exc:
            raise SchwabApiError(f"Schwab order cancellation request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SchwabApiError(f"Schwab order cancellation failed: {response.status_code} {response.text[:500]}")

    def replace_order(self, account_hash: str, order_id: str, order_payload: dict) -> None:
        if not account_hash.strip():
            raise SchwabApiError("Schwab account hash is required before replacing an order.")
        if not order_id.strip():
            raise SchwabApiError("Schwab order id is required before replacing an order.")
        url = f"{self.base_url}/trader/v1/accounts/{account_hash}/orders/{order_id}"
        try:
            with self._http_client_factory() as client:
                response = client.put(url, headers=self._headers(), json=order_payload)
        except Exception as exc:
            raise SchwabApiError(f"Schwab order replacement request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SchwabApiError(f"Schwab order replacement failed: {response.status_code} {response.text[:500]}")

    def _get_json_with_status(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int, str]:
        url = f"{self.base_url}{path}"
        try:
            with self._http_client_factory() as client:
                response = client.get(url, headers=self._headers(), params=params)
        except Exception as exc:
            raise SchwabApiError(f"Schwab market-data request failed: {exc}") from exc
        if response.status_code >= 400:
            return {}, response.status_code, response.text
        payload = response.json()
        if not isinstance(payload, dict):
            raise SchwabApiError(f"Unexpected Schwab payload type for {path}: {type(payload).__name__}")
        return payload, response.status_code, response.text

    def _get_any_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with self._http_client_factory() as client:
                response = client.get(url, headers=self._headers(), params=params)
        except Exception as exc:
            raise SchwabApiError(f"Schwab API request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SchwabApiError(f"Schwab API error for {path}: {response.status_code} {response.text[:200]}")
        return response.json()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.oauth_manager.get_access_token()}",
            "Accept": "application/json",
        }

    def _parse_chain_map(
        self,
        symbol: str,
        chain_map: dict[str, Any],
        right: OptionRight,
    ) -> list[OptionContractSnapshot]:
        contracts: list[OptionContractSnapshot] = []
        if not isinstance(chain_map, dict):
            return contracts
        for expiry_key, strikes in chain_map.items():
            expiry = _parse_expiry_key(str(expiry_key))
            if expiry is None or not isinstance(strikes, dict):
                continue
            for strike_key, entries in strikes.items():
                try:
                    strike = float(strike_key)
                except (TypeError, ValueError):
                    continue
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    try:
                        contracts.append(
                            OptionContractSnapshot(
                                symbol=symbol,
                                broker_symbol=str(entry.get("symbol", "") or "").strip(),
                                expiry=expiry,
                                strike=strike,
                                right=right,
                                bid=_optional_nonnegative_float(entry.get("bid", entry.get("bidPrice"))),
                                ask=_optional_nonnegative_float(entry.get("ask", entry.get("askPrice"))),
                                last=_optional_nonnegative_float(entry.get("last", entry.get("lastPrice"))),
                                mark=_optional_nonnegative_float(entry.get("mark", entry.get("markPrice"))),
                                implied_volatility=_optional_nonnegative_float(
                                    entry.get("volatility", entry.get("impliedVolatility"))
                                ),
                                delta=_optional_delta(entry.get("delta")),
                                gamma=_optional_float(entry.get("gamma")),
                                theta=_optional_float(entry.get("theta")),
                                open_interest=_optional_int(entry.get("openInterest")),
                                volume=_optional_int(entry.get("totalVolume", entry.get("volume"))),
                                timestamp=_timestamp_from_epoch(
                                    entry.get("quoteTimeInLong", entry.get("tradeTimeInLong"))
                                ),
                            )
                        )
                    except ValidationError:
                        LOGGER.warning("Skipping malformed Schwab option-chain entry for %s %s", symbol, expiry_key)
        return contracts


class SchwabOptionChainProvider:
    """Callable adapter matching the app's option-chain provider hook."""

    provider_kind = "schwab"
    provider_name = "Schwab Market Data"
    provider_notes = ["Read-only Schwab option-chain endpoint; order placement disabled."]

    def __init__(self, client: SchwabMarketDataClient, planner_config: OptionPlannerConfig) -> None:
        self.client = client
        self.planner_config = planner_config
        self.last_underlying_price: float | None = None

    def __call__(self, record: SignalRecord) -> Sequence[OptionContractSnapshot]:
        symbol = self.planner_config.option_symbol_for(record.payload.symbol)
        self.last_underlying_price = None
        if symbol not in self.planner_config.allowed_symbols:
            return []
        contract_type = _contract_type_for_record(record, self.planner_config)
        contracts: list[OptionContractSnapshot] = []
        for expiry in _target_expiries(self.planner_config.expiries, datetime.now(timezone.utc).date()):
            contracts.extend(self.client.get_option_chain(symbol=symbol, expiration=expiry, contract_type=contract_type))
            underlying_price = _optional_nonnegative_float(
                self.client.last_option_chain_request_params.get("underlying_price")
            )
            if underlying_price is not None and underlying_price > 0:
                self.last_underlying_price = underlying_price
        return contracts


def _merge_token_payload(current_state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    expires_in = int(payload.get("expires_in", 1800) or 1800)
    return {
        **current_state,
        "access_token": payload.get("access_token", current_state.get("access_token", "")),
        "refresh_token": payload.get("refresh_token", current_state.get("refresh_token", "")),
        "token_type": payload.get("token_type", current_state.get("token_type", "Bearer")),
        "access_token_expires_at": (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).replace(microsecond=0).isoformat(),
        "login_required": False,
        "last_auth_error": "",
    }


def _import_existing_client_credentials() -> tuple[str, str]:
    env_client_id = os.getenv("SCHWAB_CLIENT_ID", "").strip()
    env_client_secret = os.getenv("SCHWAB_CLIENT_SECRET", "").strip()
    if _is_usable_secret(env_client_id) and _is_usable_secret(env_client_secret):
        return env_client_id, env_client_secret

    for env_path in _existing_client_env_paths():
        credentials = _load_env_file_credentials(env_path)
        if credentials is not None:
            return credentials
    return "", ""


def _existing_client_env_paths() -> list[Path]:
    candidates: list[Path] = []
    for env_var in _SHARED_CLIENT_ENV_VARS:
        raw_value = os.getenv(env_var, "")
        for item in raw_value.split(os.pathsep):
            if item.strip():
                candidates.append(Path(item.strip()).expanduser())

    module_root = Path(__file__).resolve().parents[1]
    for root in (Path.cwd(), module_root):
        candidates.append(root / ".env")
        candidates.append(root.parent / _CLEAN_PROJECT_DIR_NAME / ".env")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate.resolve() if candidate.exists() else candidate.absolute()).lower()
        if marker not in seen:
            unique.append(candidate)
            seen.add(marker)
    return unique


def _load_env_file_credentials(path: Path) -> tuple[str, str] | None:
    if not path.exists() or not path.is_file():
        return None
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("export "):
            stripped = stripped[7:].strip()
        key, separator, raw_value = stripped.partition("=")
        if not separator:
            continue
        key = key.strip()
        if key not in {"SCHWAB_CLIENT_ID", "SCHWAB_CLIENT_SECRET"}:
            continue
        values[key] = _strip_env_value(raw_value)

    client_id = values.get("SCHWAB_CLIENT_ID", "")
    client_secret = values.get("SCHWAB_CLIENT_SECRET", "")
    if _is_usable_secret(client_id) and _is_usable_secret(client_secret):
        return client_id, client_secret
    return None


def _strip_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _is_usable_secret(value: str | None) -> bool:
    normalized = str(value or "").strip()
    lowered = normalized.lower()
    return bool(
        normalized
        and lowered not in _PLACEHOLDER_SECRET_VALUES
        and not lowered.startswith("your-")
        and not lowered.startswith("your_")
    )


def _schwab_live_order_gate_open(config: BridgeConfig) -> bool:
    return (
        config.service.execution_mode == "live"
        and config.service.allow_live_orders
        and config.risk.trading_enabled
    )


def _schwab_order_status_note(config: BridgeConfig, *, read_only_ready: bool) -> str:
    if _schwab_live_order_gate_open(config) and read_only_ready:
        return "Live Schwab order submission is enabled; dashboard confirmation is still required per order."
    if _schwab_live_order_gate_open(config):
        return "Live Schwab order gate is enabled, but Schwab auth is not ready."
    return "Schwab order placement is blocked by bridge execution gates."


def _schwab_chain_check_note(config: BridgeConfig, read_only_ready: bool) -> str:
    if _schwab_live_order_gate_open(config) and read_only_ready:
        return "Live Schwab order submission is enabled separately; this check is market-data only."
    return "Schwab order placement is blocked by bridge execution gates; this check is market-data only."


def _account_id_from_hash(account_hash: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", account_hash)
    suffix = compact[-8:] if len(compact) >= 8 else compact or "unknown"
    return f"schwab_{suffix.lower()}"


def _account_id_from_number(account_number: str) -> str:
    compact = re.sub(r"[^0-9A-Za-z]", "", account_number)
    return f"schwab_{compact.lower()}" if compact else "schwab_unknown"


def _mask_account_number(account_number: str) -> str:
    if not account_number:
        return "unknown"
    suffix = account_number[-4:] if len(account_number) >= 4 else account_number
    return f"***{suffix}"


def _broker_order_id_from_location(location: str) -> str:
    text = str(location or "").strip().rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _target_expiries(labels: Sequence[str], as_of_date: date) -> list[date]:
    expiries: list[date] = []
    for label in labels:
        expiry = _resolve_expiry_label(label, as_of_date)
        if expiry is not None and expiry not in expiries:
            expiries.append(expiry)
    return expiries


def _resolve_expiry_label(label: str, as_of_date: date) -> date | None:
    normalized = label.upper().strip()
    match = re.fullmatch(r"(\d+)DTE", normalized)
    if match:
        return _add_business_days(as_of_date, int(match.group(1)))
    if normalized in {"THIS_FRIDAY", "THIS FRIDAY"}:
        return _friday_for_week(as_of_date)
    if normalized in {"NEXT_WEEK_FRIDAY", "NEXT WEEK FRIDAY", "NEXT_FRIDAY"}:
        return _friday_for_week(as_of_date) + timedelta(days=7)
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _friday_for_week(as_of_date: date) -> date:
    days_until_friday = (4 - as_of_date.weekday()) % 7
    return as_of_date + timedelta(days=days_until_friday)


def _add_business_days(as_of_date: date, days: int) -> date:
    if days <= 0:
        return as_of_date
    current = as_of_date
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _right_for_direction(direction: str) -> OptionRight:
    return "CALL" if direction == "long" else "PUT"


def _contract_type_for_record(record: SignalRecord, config: OptionPlannerConfig) -> str:
    symbol = config.option_symbol_for(record.payload.symbol)
    configured = config.proposal_rights_by_symbol.get(symbol)
    if configured and set(configured) == {"CALL", "PUT"}:
        return "ALL"
    if configured and len(configured) == 1:
        return configured[0]
    return _right_for_direction(record.payload.direction)


def _is_auth_required_error(error: str) -> bool:
    normalized = error.lower()
    return any(marker in normalized for marker in ("invalid_grant", "expired", "revoked", "login is required"))


def _chain_check_sample(
    contracts: Sequence[OptionContractSnapshot],
    right: OptionRight,
    underlying_price: float | None,
) -> list[OptionContractSnapshot]:
    if not contracts:
        return []
    if underlying_price is None:
        return sorted(
            contracts,
            key=lambda contract: (
                abs(abs(contract.delta or 0.5) - 0.5),
                abs((contract.ask or contract.mark or contract.bid or 0) - (contract.bid or contract.mark or 0)),
                contract.strike,
            ),
        )[:5]

    if right == "CALL":
        candidates = [contract for contract in contracts if contract.strike >= underlying_price]
        return sorted(candidates or contracts, key=lambda contract: (abs(contract.strike - underlying_price), contract.strike))[:5]
    candidates = [contract for contract in contracts if contract.strike <= underlying_price]
    return sorted(candidates or contracts, key=lambda contract: (abs(contract.strike - underlying_price), -contract.strike))[:5]


def _extract_underlying_price(payload: dict[str, Any]) -> float | None:
    for key in ("underlyingPrice", "underlyingLastPrice", "underlyingMark"):
        price = _optional_nonnegative_float(payload.get(key))
        if price is not None and price > 0:
            return price
    underlying = payload.get("underlying")
    if isinstance(underlying, dict):
        for key in ("last", "lastPrice", "mark", "markPrice", "bid", "ask"):
            price = _optional_nonnegative_float(underlying.get(key))
            if price is not None and price > 0:
                return price
    return None


def _extract_account_balance_summary(account: dict[str, Any]) -> dict[str, Any]:
    # The "available to trade" figure depends on the account type AND on current-vs-projected:
    #   * MARGIN accounts: availableFunds is the margin-adjusted number a trader can
    #     actually deploy. cashAvailableForTrading reports gross settled cash and
    #     OVERSTATES availability (this is what made NIFTY show $301.77 instead of $70.36).
    #   * CASH accounts: cashAvailableForTrading is the settled cash available to trade.
    #   * current vs projected: Schwab's DISPLAYED "available funds" for an actively-trading
    #     account is the PROJECTED figure, which nets out pending/unsettled buys (e.g. open
    #     option scalps). The CURRENT snapshot can be higher and overstates what's deployable
    #     (Individual showed $521.87 current vs $170.54 projected, which is what Schwab shows).
    #     So we take the MINIMUM of current and projected for the chosen metric Ã¢â‚¬â€ that matches
    #     Schwab and never overstates affordability.
    raw_type = str(account.get("type", "") or account.get("accountType", "") or "").upper()
    if "MARGIN" in raw_type:
        available_keys = ("availableFunds", "cashAvailableForTrading", "availableFundsNonMarginableTrade", "cashBalance")
    else:
        # CASH (or unknown) accounts: settled tradeable cash comes first.
        available_keys = ("cashAvailableForTrading", "availableFunds", "availableFundsNonMarginableTrade", "cashBalance")
    available, available_source = _conservative_available(account, available_keys)
    buying_power, buying_power_source = _first_balance_value(
        account,
        (
            ("currentBalances", "buyingPower"),
            ("currentBalances", "dayTradingBuyingPower"),
            ("projectedBalances", "buyingPower"),
            ("initialBalances", "buyingPower"),
        ),
    )
    cash_balance, cash_balance_source = _first_balance_value(
        account,
        (
            ("currentBalances", "cashBalance"),
            ("projectedBalances", "cashBalance"),
            ("initialBalances", "cashBalance"),
        ),
    )
    return {
        "available_to_trade": available,
        "buying_power": buying_power,
        "cash_balance": cash_balance,
        "source": available_source or buying_power_source or cash_balance_source or "",
    }


def _conservative_available(
    account: dict[str, Any],
    keys: Sequence[str],
) -> tuple[float | None, str]:
    """Return the MOST CONSERVATIVE available-funds value for the first metric key present.

    For each key in priority order, look at currentBalances and projectedBalances; if either
    has the value, return the minimum of the two (projected nets out pending/unsettled
    activity, so it is usually the lower, Schwab-displayed figure). Only if neither current
    nor projected has the key do we fall back to initialBalances, then move to the next key.
    """
    current = account.get("currentBalances") if isinstance(account.get("currentBalances"), dict) else {}
    projected = account.get("projectedBalances") if isinstance(account.get("projectedBalances"), dict) else {}
    initial = account.get("initialBalances") if isinstance(account.get("initialBalances"), dict) else {}
    for key in keys:
        found: list[tuple[float, str]] = []
        for section_name, section in (("currentBalances", current), ("projectedBalances", projected)):
            value = _optional_float(section.get(key))
            if value is not None:
                found.append((value, f"{section_name}.{key}"))
        if found:
            return min(found, key=lambda item: item[0])
        initial_value = _optional_float(initial.get(key))
        if initial_value is not None:
            return initial_value, f"initialBalances.{key}"
    return None, ""


def _first_balance_value(
    account: dict[str, Any],
    paths: Sequence[tuple[str, str]],
) -> tuple[float | None, str]:
    for section_name, key in paths:
        section = account.get(section_name)
        if not isinstance(section, dict):
            continue
        value = _optional_float(section.get(key))
        if value is not None:
            return value, f"{section_name}.{key}"
    return None, ""


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.upper().replace("$", "").strip()
    if not normalized:
        raise SchwabApiError("Symbol is required for Schwab option-chain requests.")
    return normalized


def _parse_expiry_key(key: str) -> date | None:
    text = str(key).split(":", 1)[0].strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        pass
    try:
        parts = text.split("/")
        if len(parts) != 3:
            raise ValueError("invalid slash date parts")
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        if year < 100:
            year += 2000
        return date(year, month, day)
    except ValueError:
        LOGGER.warning("Unable to parse Schwab option expiry key: %s", key)
        return None


def _timestamp_from_epoch(value: Any) -> datetime:
    if value in (None, ""):
        return datetime.now(timezone.utc).replace(microsecond=0)
    try:
        epoch = float(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).replace(microsecond=0)
    if epoch > 10_000_000_000:
        epoch /= 1000
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(microsecond=0)


def _parse_datetime(raw_value: Any) -> datetime | None:
    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, datetime):
        return raw_value.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw_value))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _optional_float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _optional_nonnegative_float(value: Any) -> float | None:
    parsed = _optional_float(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _optional_delta(value: Any) -> float | None:
    parsed = _optional_float(value)
    if parsed is None or abs(parsed) > 1:
        return None
    return parsed


def _optional_int(value: Any) -> int | None:
    try:
        parsed = None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None
    if parsed is None or parsed < 0:
        return None
    return parsed
