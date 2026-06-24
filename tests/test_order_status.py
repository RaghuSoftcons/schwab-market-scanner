from __future__ import annotations

from datetime import date, datetime, timezone

from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg

from market_scanner.app import (
    _exit_target_previews,
    _extract_schwab_fill,
    _proposal_from_order_payload,
    _send_exit_target_response,
    _schwab_exit_order_payload,
    _schwab_otoco_entry_payloads,
)
from market_scanner.models import (
    ProposalOrderFillAccountStatus,
    ProposalOrderStatusResponse,
    SendExitTargetRequest,
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


def _single_leg_proposal(quantity: int = 10) -> OptionProposal:
    return OptionProposal(
        id="otoco_p",
        signal_id="scan_1",
        symbol="TLT",
        direction="long",
        structure="single",
        created_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
        expiry=date(2026, 6, 26),
        quantity=quantity,
        underlying_price=90,
        legs=[
            OptionProposalLeg(
                action="BUY",
                qty=quantity,
                symbol="TLT",
                expiry=date(2026, 6, 26),
                strike=90,
                right="CALL",
                price=1.0,
            )
        ],
        debit=quantity * 100,
        max_loss=quantity * 100,
        natural_limit_price=1.0,
        send_limit_price=1.0,
    )


def test_otoco_entry_payloads_split_and_bracket() -> None:
    payloads = _schwab_otoco_entry_payloads(_single_leg_proposal(10), 10, 1.0, [20, 50, 60], 50.0)

    assert payloads is not None
    # Front-weighted 10-lot -> 5/3/2 bracketed slices.
    assert [p["quantity"] for p in payloads] == [5, 3, 2]
    first = payloads[0]
    assert first["orderStrategyType"] == "TRIGGER"
    assert first["orderType"] == "LIMIT"
    assert first["price"] == "1.00"
    assert first["orderLegCollection"][0]["instruction"] == "BUY_TO_OPEN"
    # Child is an OCO of [target LIMIT, stop STOP], each SELL_TO_CLOSE for the slice qty.
    oco = first["childOrderStrategies"][0]
    assert oco["orderStrategyType"] == "OCO"
    target, stop = oco["childOrderStrategies"]
    assert target["orderType"] == "LIMIT" and target["price"] == "1.20"
    assert stop["orderType"] == "STOP" and stop["stopPrice"] == "0.50"
    assert target["orderLegCollection"][0]["instruction"] == "SELL_TO_CLOSE"
    assert target["quantity"] == 5 and stop["quantity"] == 5
    # Later slices carry the further targets (+50% / +60%).
    assert payloads[1]["childOrderStrategies"][0]["childOrderStrategies"][0]["price"] == "1.50"
    assert payloads[2]["childOrderStrategies"][0]["childOrderStrategies"][0]["price"] == "1.60"


def test_otoco_without_stop_degrades_to_oto() -> None:
    payloads = _schwab_otoco_entry_payloads(_single_leg_proposal(10), 10, 1.0, [20, 50, 60], 0.0)

    assert payloads is not None
    child = payloads[0]["childOrderStrategies"][0]
    # No stop -> trigger fires a single target LIMIT (OTO), not an OCO.
    assert child["orderStrategyType"] == "SINGLE"
    assert child["orderType"] == "LIMIT"


def test_otoco_skips_verticals() -> None:
    proposal = _single_leg_proposal(4).model_copy(update={"structure": "debit_vertical"})
    assert _schwab_otoco_entry_payloads(proposal, 4, 1.0, [20, 50, 60], 50.0) is None


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


def test_single_option_exit_becomes_oco_bracket_with_stop() -> None:
    # Phase 2 OCO: a single-leg option with a protective stop must produce a true
    # entry-less OCO (LIMIT profit target OCO STOP loss), both children on the same leg.
    proposal = _proposal_from_order_payload(
        proposal_id="oco_proposal",
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
    # 50% stop on a 2.50 entry -> stop trigger at 1.25; 20% target -> 3.00.
    target = _exit_target_previews(proposal, 2.5, 1, [20], stop_loss_percent=50)[0]
    assert target.stop_trigger_price == 1.25
    assert target.tos_stop_order_line.endswith("@1.25 STP GTC")

    payload = _schwab_exit_order_payload(proposal, target)

    assert payload["orderStrategyType"] == "OCO"
    children = payload["childOrderStrategies"]
    assert len(children) == 2
    target_child, stop_child = children
    assert target_child["orderType"] == "LIMIT"
    assert target_child["price"] == "3.00"
    assert stop_child["orderType"] == "STOP"
    assert stop_child["stopPrice"] == "1.25"
    # Both children close the same long leg.
    assert target_child["orderLegCollection"][0]["instruction"] == "SELL_TO_CLOSE"
    assert stop_child["orderLegCollection"][0]["instruction"] == "SELL_TO_CLOSE"


def test_single_option_exit_without_stop_stays_single_limit() -> None:
    # stop_loss_percent=0 (or unset) keeps the legacy target-only SINGLE LIMIT exit.
    proposal = _proposal_from_order_payload(
        proposal_id="no_stop_proposal",
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
    target = _exit_target_previews(proposal, 2.5, 1, [20], stop_loss_percent=0)[0]
    assert target.stop_trigger_price == 0
    payload = _schwab_exit_order_payload(proposal, target)
    assert payload["orderStrategyType"] == "SINGLE"
    assert "childOrderStrategies" not in payload


def test_vertical_exit_stays_net_credit_single_even_with_stop() -> None:
    # Verticals never become OCO here (a STOP on a NET_CREDIT spread close is unsupported).
    proposal = _proposal_from_order_payload(
        proposal_id="vertical_no_oco",
        created_at="2026-06-18T15:40:00Z",
        order_payload={
            "orderType": "NET_DEBIT",
            "complexOrderStrategyType": "VERTICAL",
            "quantity": 1,
            "price": "3.00",
            "orderLegCollection": [
                {
                    "instruction": "BUY_TO_OPEN",
                    "quantity": 1,
                    "instrument": {"symbol": "MU    260626C01195000", "assetType": "OPTION"},
                },
                {
                    "instruction": "SELL_TO_OPEN",
                    "quantity": 1,
                    "instrument": {"symbol": "MU    260626C01200000", "assetType": "OPTION"},
                },
            ],
        },
    )
    assert proposal is not None
    target = _exit_target_previews(proposal, 1.69, 1, [30], stop_loss_percent=50)[0]
    assert target.stop_trigger_price == 0
    payload = _schwab_exit_order_payload(proposal, target)
    assert payload["orderStrategyType"] == "SINGLE"
    assert payload["orderType"] == "NET_CREDIT"


def test_exit_send_response_returns_note_without_name_error() -> None:
    proposal = _proposal_from_order_payload(
        proposal_id="vertical_proposal",
        created_at="2026-06-18T15:40:00Z",
        order_payload={
            "orderType": "NET_DEBIT",
            "complexOrderStrategyType": "VERTICAL",
            "quantity": 1,
            "price": "3.00",
            "orderLegCollection": [
                {
                    "instruction": "BUY_TO_OPEN",
                    "quantity": 1,
                    "instrument": {"symbol": "MU    260626C01195000", "assetType": "OPTION"},
                },
                {
                    "instruction": "SELL_TO_OPEN",
                    "quantity": 1,
                    "instrument": {"symbol": "MU    260626C01200000", "assetType": "OPTION"},
                },
            ],
        },
    )
    assert proposal is not None
    target = _exit_target_previews(proposal, 1.69, 1, [30])[0]
    order_status = ProposalOrderStatusResponse(
        proposal_id=proposal.id,
        generated_at=datetime(2026, 6, 18, 15, 45, tzinfo=timezone.utc),
        has_filled_accounts=True,
        account_statuses=[
            ProposalOrderFillAccountStatus(
                account_id="66502618",
                account_label="Individual",
                broker_order_id="1006827658933",
                status="filled",
                schwab_status="FILLED",
                filled_quantity=1,
                remaining_quantity=0,
                average_fill_price=1.69,
                exit_targets=[target],
            )
        ],
    )

    response = _send_exit_target_response(
        proposal=proposal,
        target_index=0,
        request=SendExitTargetRequest(selected_account_ids=["66502618"], confirm_live_order=False),
        accounts=[
            type(
                "Account",
                (),
                {
                    "id": "66502618",
                    "label": "Individual",
                    "enabled": True,
                    "supports_spreads": True,
                    "account_hash": "hash",
                },
            )()
        ],
        account_notes=[],
        order_status=order_status,
        order_client=object(),
    )

    assert response.status in {"blocked", "dry_run"}
    assert response.notes
