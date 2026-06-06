from __future__ import annotations

from datetime import datetime, timezone

from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg

from market_scanner.config import _split_csv
from market_scanner.models import MarketRegime, TickerMetrics
from market_scanner.orders import schwab_order_payload
from market_scanner.scanner import candidate_score, classify_candidate


def test_symbol_splitter_accepts_commas_or_whitespace():
    assert _split_csv("AAPL,NVDA", ["SPY"]) == ["AAPL", "NVDA"]
    assert _split_csv("SPY QQQ DIA", ["AAPL"]) == ["SPY", "QQQ", "DIA"]


def test_gap_up_candidate_gets_call_bias_when_regime_not_bearish():
    metrics = TickerMetrics(
        symbol="AAPL",
        current_price=210,
        previous_close=200,
        previous_high=205,
        sma200=180,
        gap_pct=5,
        premarket_volume=100_000,
    )
    regime = MarketRegime(bias="bullish", score=1.5, symbols=[])

    action, direction, reasons, warnings = classify_candidate(
        metrics,
        regime,
        min_price=3,
        min_abs_gap_pct=0.5,
        min_premarket_volume=50_000,
    )

    assert action == "CALL_BIAS"
    assert direction == "long"
    assert "gap_up" in reasons
    assert warnings == []
    assert candidate_score(metrics, action, regime) > 0


def test_gap_down_candidate_gets_put_bias_when_regime_not_bullish():
    metrics = TickerMetrics(
        symbol="NVDA",
        current_price=940,
        previous_close=1000,
        previous_low=960,
        gap_pct=-6,
        premarket_volume=250_000,
    )
    regime = MarketRegime(bias="bearish", score=-1.2, symbols=[])

    action, direction, reasons, warnings = classify_candidate(
        metrics,
        regime,
        min_price=3,
        min_abs_gap_pct=0.5,
        min_premarket_volume=50_000,
    )

    assert action == "PUT_BIAS"
    assert direction == "short"
    assert "gap_down" in reasons
    assert warnings == []


def test_schwab_single_option_order_payload_matches_working_bridge_shape():
    proposal = OptionProposal(
        id="prop_test",
        signal_id="sig_test",
        symbol="AAPL",
        direction="long",
        structure="single",
        created_at=datetime.now(timezone.utc),
        expiry=datetime(2026, 6, 12, tzinfo=timezone.utc).date(),
        quantity=1,
        legs=[
            OptionProposalLeg(
                action="BUY",
                qty=1,
                symbol="AAPL",
                broker_symbol="AAPL  260612C00210000",
                expiry=datetime(2026, 6, 12, tzinfo=timezone.utc).date(),
                strike=210,
                right="CALL",
                price=2.4,
            )
        ],
        debit=240,
        max_loss=240,
        natural_limit_price=2.4,
        natural_debit=240,
        send_limit_price=2.7,
    )

    payload = schwab_order_payload(proposal)

    assert payload["orderType"] == "LIMIT"
    assert payload["orderLegCollection"][0]["instruction"] == "BUY_TO_OPEN"
    assert payload["orderLegCollection"][0]["instrument"]["assetType"] == "OPTION"
    assert payload["price"] == "2.70"
