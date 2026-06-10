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
        "Max Loss",
        "Entry +",
        "Target %",
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
    ]:
        assert text in response.text

    assert "Unlock" not in response.text
    assert "api-key-input" not in response.text
    assert "Build Selected" not in response.text
    assert "Refresh Proposal" not in response.text
    assert 'onclick="load()">Refresh</button>' not in response.text



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
