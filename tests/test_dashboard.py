from __future__ import annotations

from fastapi.testclient import TestClient

from market_scanner.app import app


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
        "Unlock",
        "api-key-input",
        "ITM",
        "ATM",
        "OTM",
        "trade-moneyness",
    ]:
        assert text in response.text
