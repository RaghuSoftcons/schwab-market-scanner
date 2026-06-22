"""
================================================================================
File:          gex_exits.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 16:15 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 16:15 EST

Purpose:
    Option 1: translate GEX gamma walls into concrete exit levels for a proposal.
      - Profit target  = the FAVORABLE wall (call wall for a long call, put wall
        for a long put) -> the price where dealer hedging tends to stall the move.
      - Stop           = the ADVERSE wall, BUT the implied loss is HARD-CAPPED at
        the configured max loss. The stop is always the TIGHTER of the adverse
        wall and the max-loss level, so the loss can NEVER exceed max loss.

    The underlying levels are converted to option P&L with a first-order delta
    approximation (premium change ~= delta * underlying move * 100). This is an
    estimate (ignores gamma/theta), used for guidance levels; the max-loss cap is
    exact, not an estimate.

Change Log:
    2026-06-13 16:15 EST  v1.0.0  Initial implementation (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

CONTRACT_MULTIPLIER = 100.0


@dataclass
class WallExits:
    target_underlying: Optional[float]      # favorable wall (profit target level)
    stop_underlying: Optional[float]        # adverse stop level (already capped)
    target_premium_pct: Optional[float]     # est. profit % at the target
    est_stop_loss_dollars: float            # GUARANTEED <= max_loss_dollars
    capped_by_max_loss: bool                # True if the wall stop was tightened
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "target_underlying": self.target_underlying,
            "stop_underlying": round(self.stop_underlying, 2) if self.stop_underlying else None,
            "target_premium_pct": round(self.target_premium_pct, 1) if self.target_premium_pct else None,
            "est_stop_loss_dollars": round(self.est_stop_loss_dollars, 2),
            "capped_by_max_loss": self.capped_by_max_loss,
            "notes": self.notes,
        }


def compute_wall_exits(
    *,
    direction: str,
    right: str,
    underlying_price: float,
    primary_delta: Optional[float],
    entry_premium_per_share: float,
    contracts: int,
    max_loss_dollars: float,
    call_wall: Optional[float],
    put_wall: Optional[float],
) -> Optional[WallExits]:
    """Compute capped gamma-wall exits. Returns None if inputs are unusable."""

    if (
        underlying_price <= 0
        or entry_premium_per_share <= 0
        or contracts <= 0
        or max_loss_dollars <= 0
        or primary_delta is None
        or primary_delta == 0
    ):
        return None

    delta_abs = abs(primary_delta)
    is_call_side = str(right).upper() == "CALL"

    # Favorable wall is in the trade's direction; adverse wall is against it.
    if is_call_side:  # long call -> up is favorable
        favorable_wall = call_wall if (call_wall and call_wall > underlying_price) else None
        adverse_wall = put_wall if (put_wall and put_wall < underlying_price) else None
        adverse_sign = -1.0  # adverse move is DOWN
    else:  # long put -> down is favorable
        favorable_wall = put_wall if (put_wall and put_wall < underlying_price) else None
        adverse_wall = call_wall if (call_wall and call_wall > underlying_price) else None
        adverse_sign = 1.0  # adverse move is UP

    notes: list[str] = []

    # ---- profit target from the favorable wall -----------------------------
    target_underlying: Optional[float] = None
    target_premium_pct: Optional[float] = None
    if favorable_wall is not None:
        favorable_move = abs(favorable_wall - underlying_price)
        gain_per_share = delta_abs * favorable_move
        target_premium_pct = (gain_per_share / entry_premium_per_share) * 100.0
        target_underlying = favorable_wall
        notes.append(
            f"GEX target {favorable_wall:.2f} ({'call' if is_call_side else 'put'} wall) "
            f"~ +{target_premium_pct:.0f}%"
        )

    # ---- stop from the adverse wall, HARD-CAPPED at max loss ----------------
    per_point_loss = delta_abs * CONTRACT_MULTIPLIER * contracts  # $ lost per 1.0 underlying move
    # Underlying distance at which the loss would equal max_loss.
    max_loss_distance = max_loss_dollars / per_point_loss
    cap_stop_underlying = underlying_price + adverse_sign * max_loss_distance

    if adverse_wall is not None:
        wall_distance = abs(underlying_price - adverse_wall)
        wall_loss = per_point_loss * wall_distance
        if wall_loss > max_loss_dollars:
            # Wall is too far -> tighten the stop to the max-loss level.
            stop_underlying = cap_stop_underlying
            est_stop_loss = max_loss_dollars
            capped = True
            notes.append(
                f"GEX stop tightened to {stop_underlying:.2f} (max-loss cap ${max_loss_dollars:.0f}; "
                f"{'put' if is_call_side else 'call'} wall {adverse_wall:.2f} was too far)"
            )
        else:
            stop_underlying = adverse_wall
            est_stop_loss = wall_loss
            capped = False
            notes.append(
                f"GEX stop {adverse_wall:.2f} ({'put' if is_call_side else 'call'} wall) "
                f"~ -${est_stop_loss:.0f} (within ${max_loss_dollars:.0f} max)"
            )
    else:
        # No usable adverse wall -> fall back to the max-loss stop level.
        stop_underlying = cap_stop_underlying
        est_stop_loss = max_loss_dollars
        capped = True
        notes.append(f"GEX stop at max-loss level {stop_underlying:.2f} (no adverse wall)")

    # Final invariant: the estimated stop loss can NEVER exceed max loss.
    est_stop_loss = min(est_stop_loss, max_loss_dollars)

    return WallExits(
        target_underlying=target_underlying,
        stop_underlying=stop_underlying,
        target_premium_pct=target_premium_pct,
        est_stop_loss_dollars=est_stop_loss,
        capped_by_max_loss=capped,
        notes=notes,
    )


def protective_stop_premium(
    *,
    fill_price: float,
    contracts: int,
    stop_loss_dollars: float,
    max_loss_dollars: float,
) -> Optional[float]:
    """Convert a target dollar stop loss into an option STOP trigger price, using
    the ACTUAL entry fill. The dollar loss is the tighter of the requested stop
    and the max loss, so the realized loss can NEVER exceed max loss.

        loss_at_stop = (fill_price - stop_premium) * 100 * contracts  ==  capped $

    Returns the stop premium (>= 0.01), or None if inputs are unusable.
    """

    if fill_price <= 0 or contracts <= 0 or max_loss_dollars <= 0:
        return None
    capped_loss = min(abs(stop_loss_dollars), max_loss_dollars)
    stop = fill_price - capped_loss / (CONTRACT_MULTIPLIER * contracts)
    # Round the stop price UP to the nearest cent so the realized loss is always
    # <= the cap (rounding down would let the loss creep a few dollars over).
    stop = math.ceil(stop * 100) / 100
    return max(0.01, stop)
