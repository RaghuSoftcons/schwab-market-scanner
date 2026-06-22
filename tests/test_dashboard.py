from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from market_scanner.app import _account_display_label, app
from nt_schwab_bridge.dashboard import render_dashboard_html


def test_dashboard_contains_reference_proposal_controls() -> None:
    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    for text in [
        "Current Proposal",
        "Expiry",
        "Auto",
        "Max Loss",
        "Entry +",
        "Target %",
        'expiry: "AUTO"',
        "Quote Freshness",
        "Entry Limit",
        "Exit Plan",
        "Accounts to Send",
        "Refresh Prices",
        "Build All",
        "buildCandidate(event",
        "/scan/selected/",
        "expiry_label",
        "allow_itm",
        "entry_offset_cents",
        "target_percentages",
        "/orders/status",
        "/targets/",
        "Send SELL",
        "Get Order Info",
        "fill-based closing order ready",
        "buying power",
        "ITM",
        "ATM",
        "OTM",
        "trade-moneyness",
        # New panels (#4 P&L, #9 positions, #7 automation, #6 polish)
        "Realized P&amp;L",
        "/pnl/summary",
        "/pnl/sync",
        "Sync P&amp;L",
        "Open Positions",
        "Close now",
        "/positions",
        "/close",
        "confirm_live_order",
        "Automation",
        "/automation/status",
        "/automation/tier",
        "/automation/kill",
        "Release kill",
        "Mute",
        "scanner_sound_muted",
        "speechSynthesis",
        "Stop @",
        "tos_stop_order_line",
        "score-breakdown",
    ]:
        assert text in response.text

    assert "Unlock" not in response.text
    assert "api-key-input" not in response.text
    assert "Build Selected" not in response.text
    assert "Refresh Proposal" not in response.text
    assert 'onclick="load()">Refresh</button>' not in response.text



def test_dashboard_injects_api_key_for_protected_posts() -> None:
    from market_scanner.dashboard import dashboard_html

    # No key configured -> empty literal, authOptions sends no header (unchanged behavior).
    no_key = dashboard_html()
    assert 'const SCANNER_API_KEY = "";' in no_key
    assert "__SCANNER_API_KEY__" not in no_key
    assert 'opts.headers["X-API-Key"] = SCANNER_API_KEY' in no_key

    # Key configured -> injected as a safe JS string literal; authOptions will attach it.
    with_key = dashboard_html("secret-abc123")
    assert 'const SCANNER_API_KEY = "secret-abc123";' in with_key

    # Quotes/backslashes in the key are escaped (no JS break-out).
    tricky = dashboard_html('a"b\\c')
    assert r'const SCANNER_API_KEY = "a\"b\\c";' in tricky
    assert "__SCANNER_API_KEY__" not in tricky


def test_dashboard_route_passes_configured_api_key() -> None:
    from market_scanner.app import app, settings

    original = settings.service.api_key
    try:
        settings.service.api_key = "route-key-xyz"
        html = TestClient(app).get("/dashboard").text
        assert 'const SCANNER_API_KEY = "route-key-xyz";' in html
    finally:
        settings.service.api_key = original


def test_bridge_dashboard_trade_cards_include_moneyness_badges() -> None:
    html = render_dashboard_html()

    assert "trade-labels" in html
    assert "trade-moneyness" in html
    assert "proposalMoneyness" in html
    assert "moneynessTone" in html
    assert "Trade #${index + 1}" in html

def test_account_aliases_match_tos_names() -> None:
    assert (
        _account_display_label(
            SimpleNamespace(account_number="19900410SCHW", label="Schwab ****0410", id="hash-1")
        )
        == "Grow Fly 9999"
    )
    assert (
        _account_display_label(
            SimpleNamespace(account_number="", label="Schwab ****2523", id="hash-2")
        )
        == "Raghu - Roth"
    )
