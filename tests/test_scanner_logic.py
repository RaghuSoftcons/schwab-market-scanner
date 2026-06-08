from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from nt_schwab_bridge.models import OptionContractSnapshot, OptionProposal, OptionProposalLeg

from market_scanner.app import _is_simulated_proposal
from market_scanner.config import _split_csv
from market_scanner.models import Candle, EquityQuote, MarketRegime, TickerMetrics
from market_scanner.orders import schwab_order_payload
from market_scanner.schwab_ext import _parse_quote
from market_scanner.scanner import (
    _session,
    _signal_record,
    _simulated_fallback_proposals,
    _simulated_replay_expiries,
    candidate_score,
    classify_candidate,
    compute_metrics,
)


def test_symbol_splitter_accepts_commas_or_whitespace():
    assert _split_csv("AAPL,NVDA", ["SPY"]) == ["AAPL", "NVDA"]
    assert _split_csv("SPY QQQ DIA", ["AAPL"]) == ["SPY", "QQQ", "DIA"]


def test_replay_metrics_ignore_future_intraday_bars():
    tz = ZoneInfo("America/New_York")
    as_of = datetime(2026, 6, 5, 9, 29, tzinfo=tz).astimezone(timezone.utc)
    daily = [
        Candle(
            timestamp=datetime(2026, 6, 4, 16, 0, tzinfo=tz).astimezone(timezone.utc),
            open=98,
            high=101,
            low=97,
            close=100,
            volume=1_000_000,
        )
    ]
    intraday = [
        Candle(
            timestamp=datetime(2026, 6, 5, 9, 0, tzinfo=tz).astimezone(timezone.utc),
            open=104,
            high=106,
            low=103,
            close=105,
            volume=50_000,
        ),
        Candle(
            timestamp=datetime(2026, 6, 5, 15, 59, tzinfo=tz).astimezone(timezone.utc),
            open=118,
            high=121,
            low=117,
            close=120,
            volume=500_000,
        ),
    ]

    metrics = compute_metrics(
        symbol="AAPL",
        quote=None,
        intraday=intraday,
        daily=daily,
        as_of=as_of,
        timezone_name="America/New_York",
    )

    assert metrics.current_price == 105
    assert metrics.gap_pct == 5
    assert metrics.premarket_high == 106
    assert metrics.today_high is None


def test_sunday_evening_is_overnight_session():
    tz = ZoneInfo("America/New_York")
    as_of = datetime(2026, 6, 7, 20, 15, tzinfo=tz)

    assert _session(as_of, "America/New_York") == "overnight"


def test_schwab_extended_quote_time_is_parsed():
    quote = _parse_quote(
        "NVDA",
        {
            "extended": {
                "bidPrice": 207.66,
                "askPrice": 207.78,
                "lastPrice": 207.74,
                "quoteTime": 1780880306406,
                "tradeTime": 1780880305000,
            },
            "quote": {"lastPrice": 204.03},
            "regular": {"regularMarketLastPrice": 205.1},
        },
    )

    assert quote.last == 207.74
    assert quote.timestamp is not None


def test_schwab_quote_parser_uses_newer_quote_when_extended_is_stale():
    quote = _parse_quote(
        "MU",
        {
            "extended": {
                "bidPrice": 0.0,
                "askPrice": 0.0,
                "lastPrice": 895.9,
                "mark": 0.0,
                "quoteTime": 0,
                "tradeTime": 1780905599000,
            },
            "quote": {
                "bidPrice": 898.0,
                "askPrice": 899.2,
                "lastPrice": 898.15,
                "mark": 898.0,
                "quoteTime": 1780910917730,
                "tradeTime": 1780910917980,
            },
        },
    )

    assert quote.bid == 898.0
    assert quote.ask == 899.2
    assert quote.last == 898.15
    assert quote.mark == 898.0


def test_metrics_use_bid_ask_midpoint_for_live_quote_price():
    tz = ZoneInfo("America/New_York")
    as_of = datetime(2026, 6, 8, 5, 30, tzinfo=tz).astimezone(timezone.utc)
    daily = [
        Candle(
            timestamp=datetime(2026, 6, 5, 16, 0, tzinfo=tz).astimezone(timezone.utc),
            open=860,
            high=875,
            low=850,
            close=864,
            volume=1_000_000,
        )
    ]
    quote = EquityQuote(
        symbol="MU",
        bid=899.05,
        ask=899.55,
        last=895.9,
        timestamp=as_of,
    )

    metrics = compute_metrics(
        symbol="MU",
        quote=quote,
        intraday=[],
        daily=daily,
        as_of=as_of,
        timezone_name="America/New_York",
    )

    assert metrics.current_price == 899.3
    assert metrics.gap_pct == 4.0856


def test_simulated_fallback_proposal_is_marked_sim_only():
    scanned_at = datetime(2026, 6, 5, 13, 29, tzinfo=timezone.utc)
    metrics = TickerMetrics(symbol="AAPL", current_price=312.84)
    record = _signal_record("AAPL", "long", metrics, scanned_at)
    chain = [
        OptionContractSnapshot(
            symbol="AAPL",
            broker_symbol="AAPL  260608C00315000",
            expiry=date(2026, 6, 8),
            strike=315,
            right="CALL",
            bid=2.1,
            ask=2.35,
            mark=2.25,
            delta=0.42,
            open_interest=0,
            timestamp=datetime(2026, 6, 6, 20, 0, tzinfo=timezone.utc),
        )
    ]

    proposals = _simulated_fallback_proposals(record, chain, metrics, scanned_at)

    assert len(proposals) == 1
    assert proposals[0].id.startswith("sim_")
    assert "SIM_ONLY" in proposals[0].reasons
    assert _is_simulated_proposal(proposals[0])


def test_simulated_replay_expiries_include_next_business_day_and_next_friday():
    assert _simulated_replay_expiries(date(2026, 6, 5)) == [
        date(2026, 6, 8),
        date(2026, 6, 12),
    ]


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
