"""
File: test_score_and_gex.py
Created: 2026-06-22 18:10 EST
Author: Claude (Anthropic) + Raghu
Version: 1.0.0
Last Modified: 2026-06-22 18:10 EST

Change Log:
- 2026-06-22 18:10 EST | 1.0.0 | Phase 2/3 of the Unified-Platform restyle: planner score
  breakdown (value/max components) and GEX wall stamping on proposals (gated by NT_GEX_WALL_EXITS).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from market_scanner.config import load_settings
from market_scanner.scanner import _apply_gex_walls
from nt_schwab_bridge.models import OptionContractSnapshot, OptionProposal, OptionProposalLeg
from nt_schwab_bridge.planner import OptionProposalPlanner, _BASE_SCORE_LABELS


def _planner() -> OptionProposalPlanner:
    return OptionProposalPlanner(load_settings().settings.planner_config())


def _contract(strike, right, delta=0.5, gamma=0.02, oi=2000, bid=4.1, ask=4.3):
    return OptionContractSnapshot(
        symbol="QQQ", broker_symbol=f"QQQ   260626{('C' if right=='CALL' else 'P')}{int(strike*1000):08d}",
        expiry=date(2026, 6, 26), strike=strike, right=right, bid=bid, ask=ask, mark=(bid + ask) / 2,
        delta=delta, gamma=gamma, open_interest=oi, volume=1000, timestamp=datetime.now(timezone.utc),
    )


def test_score_breakdown_components_sum_to_score() -> None:
    planner = _planner()
    components = planner._score_components([_contract(540, "CALL")], debit=420.0, expiry_label="THIS_FRIDAY")
    assert set(components) == {"delta", "liquidity", "oi", "debit"}
    breakdown = planner._base_breakdown(components)
    assert [r["label"] for r in breakdown] == [lbl for _k, lbl, _m in _BASE_SCORE_LABELS]
    assert [r["max"] for r in breakdown] == [m for _k, _l, m in _BASE_SCORE_LABELS]
    assert all(r["kind"] == "base" for r in breakdown)
    # Each value within its max, and the rounded total matches _score().
    assert all(0 <= r["value"] <= r["max"] for r in breakdown)
    assert round(sum(components.values()), 4) == planner._score([_contract(540, "CALL")], debit=420.0, expiry_label="THIS_FRIDAY")


def _proposal(underlying=540.0):
    leg = OptionProposalLeg(action="BUY", qty=1, symbol="QQQ", expiry=date(2026, 6, 26), strike=540, right="CALL", price=4.3, delta=0.5)
    leg = leg.model_copy(update={"broker_symbol": "QQQ   260626C00540000"})
    return OptionProposal(
        id="p1", signal_id="s1", symbol="QQQ", direction="long", structure="single",
        created_at=datetime.now(timezone.utc), expiry=date(2026, 6, 26), quantity=1,
        underlying_price=underlying, legs=[leg], debit=430, max_loss=430, send_limit_price=4.30,
    )


def _gamma_chain():
    # Call wall above spot, put wall below spot (highest-gamma strikes).
    return [
        _contract(545, "CALL", delta=0.45, gamma=0.05, oi=8000),
        _contract(550, "CALL", delta=0.30, gamma=0.02, oi=3000),
        _contract(535, "PUT", delta=-0.45, gamma=0.05, oi=9000),
        _contract(530, "PUT", delta=-0.30, gamma=0.02, oi=4000),
    ]


def test_gex_walls_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("NT_GEX_WALL_EXITS", raising=False)
    out = _apply_gex_walls([_proposal()], _gamma_chain(), 540.0)
    assert out[0].gex_target_underlying is None and out[0].gex_stop_underlying is None


def test_gex_walls_stamped_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("NT_GEX_WALL_EXITS", "true")
    out = _apply_gex_walls([_proposal()], _gamma_chain(), 540.0)
    p = out[0]
    # Call wall (545) feeds the long-call target; stop is set and capped at/below max loss.
    assert p.gex_target_underlying is not None
    assert p.gex_stop_loss_dollars is not None
    assert p.gex_stop_loss_dollars <= p.max_loss + 1e-6
