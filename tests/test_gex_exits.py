"""
================================================================================
File:          test_gex_exits.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 16:15 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 16:15 EST

Purpose:
    Tests gamma-wall exit levels, with emphasis on the hard invariant the user
    requires: the estimated stop loss must NEVER exceed the configured max loss.

Change Log:
    2026-06-13 16:15 EST  v1.0.0  Initial tests (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

from nt_schwab_bridge.gex_exits import compute_wall_exits, protective_stop_premium


def _long_call(**over):
    base = dict(
        direction="long",
        right="CALL",
        underlying_price=620.0,
        primary_delta=0.50,
        entry_premium_per_share=2.85,
        contracts=1,
        max_loss_dollars=285.0,  # = full premium of 1 contract
        call_wall=624.0,
        put_wall=617.0,
    )
    base.update(over)
    return compute_wall_exits(**base)


def test_long_call_target_from_call_wall():
    ex = _long_call()
    assert ex is not None
    assert ex.target_underlying == 624.0
    # gain ~= 0.50 * (624-620) = 2.00/share on 2.85 premium ~= 70%
    assert 65 <= ex.target_premium_pct <= 75


def test_long_call_stop_uses_put_wall_when_within_max():
    # put wall 617 -> loss ~= 0.50*(620-617)*100 = $150 < $285 max
    ex = _long_call()
    assert ex.stop_underlying == 617.0
    assert ex.est_stop_loss_dollars <= 285.0
    assert ex.capped_by_max_loss is False


def test_stop_loss_never_exceeds_max_when_wall_far():
    # put wall very far (590) would imply 0.50*(620-590)*100 = $1500 loss,
    # but max loss is $285 -> stop must tighten and loss is capped.
    ex = _long_call(put_wall=590.0)
    assert ex.capped_by_max_loss is True
    assert ex.est_stop_loss_dollars == 285.0
    # The tightened stop sits above the far wall (closer to spot).
    assert ex.stop_underlying > 590.0
    assert ex.stop_underlying < 620.0


def test_invariant_loss_never_exceeds_max_across_many_inputs():
    for put_wall in [619, 617, 610, 600, 580, 500]:
        for contracts in [1, 2, 3]:
            for max_loss in [200, 285, 500]:
                ex = _long_call(put_wall=put_wall, contracts=contracts, max_loss_dollars=max_loss)
                assert ex.est_stop_loss_dollars <= max_loss + 1e-6


def test_long_put_mirrors_sides():
    # Bearish: favorable wall is the put wall (below), adverse is the call wall.
    ex = compute_wall_exits(
        direction="short",
        right="PUT",
        underlying_price=620.0,
        primary_delta=-0.50,
        entry_premium_per_share=2.85,
        contracts=1,
        max_loss_dollars=285.0,
        call_wall=623.0,
        put_wall=616.0,
    )
    assert ex.target_underlying == 616.0          # profit toward put wall
    assert ex.stop_underlying == 623.0            # stop toward call wall
    assert ex.est_stop_loss_dollars <= 285.0


def test_no_adverse_wall_falls_back_to_max_loss_stop():
    # put wall above spot -> not a valid adverse wall for a long call.
    ex = _long_call(put_wall=621.0)
    assert ex.capped_by_max_loss is True
    assert ex.est_stop_loss_dollars == 285.0


def test_returns_none_on_bad_inputs():
    assert _long_call(primary_delta=0.0) is None
    assert _long_call(entry_premium_per_share=0.0) is None
    assert _long_call(max_loss_dollars=0.0) is None


def _loss_at(fill, stop, contracts):
    return (fill - stop) * 100 * contracts


def test_protective_stop_realizes_requested_loss_when_within_max():
    # Want a $150 stop on 1 contract filled at $2.85.
    stop = protective_stop_premium(
        fill_price=2.85, contracts=1, stop_loss_dollars=150, max_loss_dollars=285
    )
    assert abs(_loss_at(2.85, stop, 1) - 150) <= 1.0


def test_protective_stop_never_exceeds_max_loss():
    # Requested stop ($900) is larger than max ($285) -> clamp to max.
    stop = protective_stop_premium(
        fill_price=2.85, contracts=1, stop_loss_dollars=900, max_loss_dollars=285
    )
    assert _loss_at(2.85, stop, 1) <= 285 + 1.0


def test_protective_stop_invariant_sweep():
    for fill in [1.0, 2.85, 5.0]:
        for contracts in [1, 2, 3]:
            for want in [50, 150, 500, 5000]:
                for cap in [200, 285, 500]:
                    stop = protective_stop_premium(
                        fill_price=fill, contracts=contracts,
                        stop_loss_dollars=want, max_loss_dollars=cap,
                    )
                    assert stop is not None
                    assert _loss_at(fill, stop, contracts) <= cap + 1e-6


def test_protective_stop_bad_inputs_return_none():
    assert protective_stop_premium(fill_price=0, contracts=1, stop_loss_dollars=100, max_loss_dollars=200) is None
    assert protective_stop_premium(fill_price=2.5, contracts=0, stop_loss_dollars=100, max_loss_dollars=200) is None


def test_exit_preview_uses_protective_stop_within_max(monkeypatch):
    # Scanner port: GEX wall exits feed the OCO stop via market_scanner.app._exit_target_previews,
    # which takes target_percentages (not the proposal's exit_targets list).
    from datetime import date, datetime, timezone

    from market_scanner.app import _exit_target_previews
    from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg

    monkeypatch.setenv("NT_GEX_WALL_EXITS", "true")
    now = datetime.now(timezone.utc)
    leg = OptionProposalLeg(action="BUY", symbol="SPY", expiry=date.today(), strike=620,
                            right="CALL", qty=2, price=2.85)

    def _preview(gex_stop_dollars, pct=50.0):
        prop = OptionProposal(
            id="p1", signal_id="s1", symbol="SPY", direction="long", structure="single",
            created_at=now, expiry=date.today(), quantity=2, legs=[leg], debit=570, max_loss=570,
            gex_stop_loss_dollars=gex_stop_dollars,
        )
        p = _exit_target_previews(prop, 2.85, 2, [40.0], stop_loss_percent=pct)[0]
        return (2.85 - p.stop_trigger_price) * 100 * 2  # realized loss at the stop

    # 50% SL on a $2.85 entry => ~$285 loss. That is the protective FLOOR.
    # GEX wall TIGHTER ($100) -> GEX wins (smaller loss).
    assert abs(_preview(100.0) - 100) <= 5
    # GEX wall FARTHER ($500) -> the 50% floor wins (never looser than ~$285).
    assert abs(_preview(500.0) - 285) <= 6
    # Either way, never exceeds max loss.
    assert _preview(500.0) <= 570 + 1e-6


def test_exit_preview_flag_off_uses_percent_stop(monkeypatch):
    from datetime import date, datetime, timezone

    from market_scanner.app import _exit_target_previews
    from nt_schwab_bridge.models import OptionProposal, OptionProposalLeg

    monkeypatch.delenv("NT_GEX_WALL_EXITS", raising=False)
    now = datetime.now(timezone.utc)
    leg = OptionProposalLeg(action="BUY", symbol="SPY", expiry=date.today(), strike=620,
                            right="CALL", qty=2, price=2.85)
    prop = OptionProposal(
        id="p1", signal_id="s1", symbol="SPY", direction="long", structure="single",
        created_at=now, expiry=date.today(), quantity=2, legs=[leg], debit=570, max_loss=570,
        gex_stop_loss_dollars=300.0,
    )
    preview = _exit_target_previews(prop, 2.85, 2, [40.0], stop_loss_percent=50.0)[0]
    # Flag off -> the classic 50% stop: 2.85 * 0.5 = 1.42 (rounded).
    assert abs(preview.stop_trigger_price - 1.42) <= 0.02
