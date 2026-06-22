"""
================================================================================
File:          gex.py
Project:       Unified Trading Platform with Schwab  (nt-bridge-v2)
Created:       2026-06-13 15:25 EST
Author:        Claude (Anthropic) + Raghu
Version:       1.0.0
Last Modified: 2026-06-13 15:25 EST

Purpose:
    Computes Gamma Exposure (GEX) for the GEX overlay (brief Step 6, item 4).
    IMPORTANT: GEX is NOT a value Schwab or thinkorswim hands you -- it is
    DERIVED from the option chain. We compute it from the SAME Schwab option
    chain the bridge already fetches to build proposals (calls/puts with gamma
    and open interest), so NO new data feed is required.

    Convention (SpotGamma-style, simplified):
        net_gex = Σ(gamma_call · OI_call · 100 · spot)
                - Σ(gamma_put  · OI_put  · 100 · spot)

      * net_gex > 0  -> dealers net LONG gamma -> price-pinning / mean-reverting
        regime: tends to SUPPRESS momentum. For a breakout/momentum signal this
        is a HEADWIND -> "opposes".
      * net_gex < 0  -> dealers net SHORT gamma -> moves get AMPLIFIED /
        trend-extending: a TAILWIND for momentum signals -> "supports".

    The NT indicators here (IntraBarBreakoutRetest, TwoLeggedPullback,
    UltimateAIPro) are momentum/breakout strategies, so the mapping above is the
    default. A neutral band around zero leaves the score unchanged. The thresholds
    are configurable so you can tune to your instruments.

Change Log:
    2026-06-13 15:25 EST  v1.0.0  Initial implementation (Claude + Raghu).
================================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Optional

CONTRACT_MULTIPLIER = 100.0

GexRegime = Literal["positive", "negative", "neutral"]
GexSupport = Literal["supports", "opposes", "neutral"]


@dataclass
class OptionGreekRow:
    """Minimal per-contract inputs needed for GEX (extracted from the Schwab chain)."""

    is_call: bool
    strike: float
    gamma: float
    open_interest: int


@dataclass
class GexConfig:
    # |net_gex| below this (absolute, in $ of gamma per 1% move) is "neutral".
    neutral_band: float = 0.0
    # Momentum strategies: negative GEX supports, positive GEX opposes.
    momentum_strategy: bool = True
    # Ignore strikes with open interest below this (guide recommends ~100).
    min_open_interest: int = 0


@dataclass
class StrikeGex:
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float

    def as_dict(self) -> dict:
        return {
            "strike": self.strike,
            "call_gex": round(self.call_gex, 2),
            "put_gex": round(self.put_gex, 2),
            "net_gex": round(self.net_gex, 2),
        }


@dataclass
class GexResult:
    net_gex: float
    regime: GexRegime
    support: GexSupport
    call_gex: float
    put_gex: float
    contracts_used: int
    per_strike: list[StrikeGex] = None  # type: ignore[assignment]
    call_wall: float | None = None      # strike with the most call gamma (resistance/target)
    put_wall: float | None = None       # strike with the most put gamma (floor/stop)
    gamma_flip: float | None = None     # ESTIMATE only (see _walls_and_flip)

    def as_dict(self) -> dict:
        return {
            "net_gex": round(self.net_gex, 2),
            "regime": self.regime,
            "support": self.support,
            "call_gex": round(self.call_gex, 2),
            "put_gex": round(self.put_gex, 2),
            "contracts_used": self.contracts_used,
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "gamma_flip_estimate": self.gamma_flip,
            "per_strike": [s.as_dict() for s in (self.per_strike or [])],
        }


def compute_gex(
    rows: Iterable[OptionGreekRow],
    spot: float,
    config: GexConfig | None = None,
) -> GexResult:
    """Compute net dealer GEX, per-strike GEX, gamma walls, a gamma-flip estimate,
    and the momentum support verdict from chain rows."""

    cfg = config or GexConfig()
    by_strike: dict[float, dict[str, float]] = {}
    call_gex = 0.0
    put_gex = 0.0
    used = 0
    for row in rows:
        gamma = row.gamma
        oi = row.open_interest
        if gamma is None or oi is None or gamma <= 0 or oi <= 0:
            continue
        if oi < cfg.min_open_interest:
            continue
        contribution = gamma * oi * CONTRACT_MULTIPLIER * spot
        bucket = by_strike.setdefault(row.strike, {"call": 0.0, "put": 0.0})
        if row.is_call:
            call_gex += contribution
            bucket["call"] += contribution
        else:
            put_gex += contribution
            bucket["put"] += contribution
        used += 1

    net = call_gex - put_gex

    per_strike = [
        StrikeGex(strike=strike, call_gex=v["call"], put_gex=v["put"], net_gex=v["call"] - v["put"])
        for strike, v in sorted(by_strike.items())
    ]
    call_wall, put_wall, gamma_flip = _walls_and_flip(per_strike)

    if abs(net) <= cfg.neutral_band:
        regime: GexRegime = "neutral"
    elif net > 0:
        regime = "positive"
    else:
        regime = "negative"

    support: GexSupport = _support_for(regime, cfg)
    return GexResult(
        net_gex=net,
        regime=regime,
        support=support,
        call_gex=call_gex,
        put_gex=put_gex,
        contracts_used=used,
        per_strike=per_strike,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
    )


def _walls_and_flip(
    per_strike: list["StrikeGex"],
) -> tuple[float | None, float | None, float | None]:
    """Gamma walls + a gamma-flip ESTIMATE.

    - Call wall  = strike with the most call gamma (acts as resistance/target).
    - Put wall   = strike with the most put gamma  (acts as floor/stop).
    - Gamma flip = APPROXIMATE zero-gamma strike: the boundary where the running
      cumulative net GEX (summed low->high strike) crosses zero. A precise flip
      requires re-pricing gamma across spot (or a dedicated exposure API); this
      snapshot-based value is an estimate only.
    """

    if not per_strike:
        return None, None, None

    call_wall = max(per_strike, key=lambda s: s.call_gex).strike
    put_wall = max(per_strike, key=lambda s: s.put_gex).strike

    # Flip estimate: the strike boundary where per-strike net GEX transitions from
    # put-dominated (negative, typically below spot) to call-dominated (positive,
    # above spot). Linear-interpolate between the two bracketing strikes.
    flip: float | None = None
    prev = None
    for s in per_strike:
        if prev is not None and (prev.net_gex < 0) != (s.net_gex < 0):
            span = s.net_gex - prev.net_gex
            flip = prev.strike if span == 0 else prev.strike + (s.strike - prev.strike) * (
                -prev.net_gex / span
            )
            break
        prev = s
    return call_wall, put_wall, flip


def _support_for(regime: GexRegime, cfg: GexConfig) -> GexSupport:
    if regime == "neutral":
        return "neutral"
    if cfg.momentum_strategy:
        # negative GEX -> amplifies moves -> supports momentum; positive -> opposes
        return "supports" if regime == "negative" else "opposes"
    # mean-reversion strategy would invert this
    return "opposes" if regime == "negative" else "supports"


def gex_support_from_schwab_chain(
    chain_contracts: Iterable[object],
    spot: float,
    config: GexConfig | None = None,
) -> Optional[str]:
    """Adapter: derive the GEX support verdict from Schwab chain snapshot objects.

    Accepts any objects exposing `gamma`, `open_interest`, and a call/put marker
    (`right` == "CALL"/"PUT", or boolean `is_call`). Returns "supports" /
    "opposes" / "neutral" suitable for `signal_enrichment.enrich(gex_support=...)`,
    or None if the chain lacks gamma/OI data.
    """

    result = gex_result_from_schwab_chain(chain_contracts, spot, config)
    return result.support if result is not None else None


def _rows_from_schwab_chain(chain_contracts: Iterable[object]) -> list[OptionGreekRow]:
    rows: list[OptionGreekRow] = []
    for c in chain_contracts:
        gamma = getattr(c, "gamma", None)
        oi = getattr(c, "open_interest", None)
        if gamma is None or oi is None:
            continue
        right = str(getattr(c, "right", "")).upper()
        is_call = getattr(c, "is_call", None)
        if is_call is None:
            is_call = right == "CALL"
        strike = float(getattr(c, "strike", 0) or 0)
        rows.append(
            OptionGreekRow(is_call=bool(is_call), strike=strike, gamma=float(gamma), open_interest=int(oi))
        )
    return rows


def gex_result_from_schwab_chain(
    chain_contracts: Iterable[object],
    spot: float,
    config: GexConfig | None = None,
) -> Optional[GexResult]:
    """Full GEX result (net, regime, support, walls, flip estimate, per-strike)
    from Schwab chain snapshot objects, or None if the chain lacks gamma/OI."""

    rows = _rows_from_schwab_chain(chain_contracts)
    if not rows:
        return None
    return compute_gex(rows, spot, config)
