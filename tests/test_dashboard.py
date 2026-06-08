from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from market_scanner.app import _account_display_label, app


def test_dashboard_contains_reference_proposal_controls() -> None:
    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    for text in [
        "Current Proposal",
        "Expiry",
        "Max Loss",
        "Entry +",
        "Targets",
        "Quote Freshness",
        "Entry Limit",
        "Exit Plan",
        "Accounts to Send",
        "Refresh Prices",
        "Build Selected",
        "/scan/selected/",
        "ITM",
        "ATM",
        "OTM",
        "trade-moneyness",
    ]:
        assert text in response.text

    assert "Unlock" not in response.text
    assert "api-key-input" not in response.text
    assert "Refresh Proposal" not in response.text
    assert 'onclick="load()">Refresh</button>' not in response.text


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
