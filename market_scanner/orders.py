from __future__ import annotations

from nt_schwab_bridge.models import OptionProposal


def schwab_order_payload(proposal: OptionProposal, limit_price: float | None = None) -> dict:
    order_price = limit_price if limit_price is not None else (
        proposal.send_limit_price
        if proposal.send_limit_price is not None
        else proposal.debit / (proposal.quantity * 100)
    )
    return {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "NET_DEBIT" if proposal.structure == "debit_vertical" else "LIMIT",
        "complexOrderStrategyType": "VERTICAL" if proposal.structure == "debit_vertical" else "NONE",
        "quantity": proposal.quantity,
        "price": f"{order_price:.2f}",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "BUY_TO_OPEN" if leg.action == "BUY" else "SELL_TO_OPEN",
                "quantity": leg.qty,
                "instrument": {
                    "symbol": leg.broker_symbol or fallback_broker_option_symbol(leg),
                    "assetType": "OPTION",
                },
            }
            for leg in proposal.legs
        ],
    }


def fallback_broker_option_symbol(leg) -> str:
    compact_strike = f"{int(round(float(leg.strike) * 1000)):08d}"
    return f"{leg.symbol.upper():<6}{leg.expiry:%y%m%d}{leg.right[0]}{compact_strike}"
