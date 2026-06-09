from __future__ import annotations

from datetime import date, datetime, timezone

from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg

from market_scanner.app import (
    _exit_target_previews,
    _extract_schwab_fill,
    _proposal_from_order_payload,
    _schwab_exit_order_payload,
)


def test_filled_order_creates_fill_based_exit_preview() -> None:
    proposal = OptionProposal(
        id="proposal_1",
        signal_id="scan_1",
        symbol="PLTR",
        direction="long",
        structure="single",
        created_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
        expiry=date(2026, 6, 12),
        quantity=2,
        underlying_price=120,
        legs=[
            OptionProposalLeg(
                action="BUY",
                qty=2,
                symbol="PLTR",
                expiry=date(2026, 6, 12),
                strike=120,
                right="CALL",
                price=2.4,
            )
        ],
        debit=480,
        max_loss=480,
        natural_limit_price=2.4,
        send_limit_price=2.5,
    )
    fill = _extract_schwab_fill(
        {
            "status": "FILLED",
            "filledQuantity": 2,
            "remainingQuantity": 0,
            "averagePrice": 2.5,
        },
        proposal,
    )

    targets = _exit_target_previews(proposal, fill["average_fill_price"], fill["filled_quantity"], [25, 50, 60])

    assert fill["status"] == "filled"
    assert len(targets) == 2
    assert targets[0].target_limit_price == 3.12
    assert targets[0].estimated_profit == 62
    assert targets[0].tos_exit_order_line.startswith("SELL -1 SINGLE PLTR 100 12 JUN 26 120 CALL @3.12 LMT GTC")


def test_order_payload_restores_proposal_for_older_audit_events() -> None:
    proposal = _proposal_from_order_payload(
        proposal_id="old_proposal",
        created_at="2026-06-08T15:40:00Z",
        order_payload={
            "session": "NORMAL",
            "duration": "DAY",
            "orderType": "LIMIT",
            "complexOrderStrategyType": "NONE",
            "quantity": 1,
            "price": "2.50",
            "orderStrategyType": "SINGLE",
            "orderLegCollection": [
                {
                    "instruction": "BUY_TO_OPEN",
                    "quantity": 1,
                    "instrument": {
                        "symbol": "PLTR  260612C00120000",
                        "assetType": "OPTION",
                    },
                }
            ],
        },
    )

    assert proposal is not None
    assert proposal.symbol == "PLTR"
    assert proposal.expiry == date(2026, 6, 12)
    assert proposal.legs[0].strike == 120
    assert proposal.max_loss == 250


def test_exit_order_payload_closes_single_option() -> None:
    proposal = _proposal_from_order_payload(
        proposal_id="old_proposal",
        created_at="2026-06-08T15:40:00Z",
        order_payload={
            "orderType": "LIMIT",
            "complexOrderStrategyType": "NONE",
            "quantity": 1,
            "price": "2.50",
            "orderLegCollection": [
                {
                    "instruction": "BUY_TO_OPEN",
                    "quantity": 1,
                    "instrument": {"symbol": "PLTR  260612C00120000", "assetType": "OPTION"},
                }
            ],
        },
    )
    assert proposal is not None
    target = _exit_target_previews(proposal, 2.5, 1, [20])[0]

    payload = _schwab_exit_order_payload(proposal, target)

    assert payload["duration"] == "GOOD_TILL_CANCEL"
    assert payload["orderType"] == "LIMIT"
    assert payload["price"] == "3.00"
    assert payload["orderLegCollection"][0]["instruction"] == "SELL_TO_CLOSE"
