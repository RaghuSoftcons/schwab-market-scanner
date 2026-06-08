from __future__ import annotations

from datetime import date, datetime, timezone

from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg

from market_scanner.app import _exit_target_previews, _extract_schwab_fill


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
