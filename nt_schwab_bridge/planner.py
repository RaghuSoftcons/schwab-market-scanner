"""Dry-run option proposal planner for accepted NT signals."""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Sequence

from nt_schwab_bridge.config import OptionPlannerConfig
from nt_schwab_bridge.models import (
    Direction,
    OptionCandidateDiagnostic,
    OptionContractSnapshot,
    OptionProposal,
    OptionProposalExitTarget,
    OptionProposalLeg,
    OptionProposalResult,
    OptionQuoteFreshness,
    OptionRight,
    ProposalLegAction,
    SignalRecord,
)


class OptionProposalPlanner:
    """Build ranked dry-run option proposals from normalized signal records."""

    def __init__(self, config: OptionPlannerConfig | None = None) -> None:
        self.config = config or OptionPlannerConfig()

    def plan(
        self,
        signal: SignalRecord,
        chain: Sequence[OptionContractSnapshot],
        as_of: datetime | None = None,
        underlying_price: float | None = None,
    ) -> OptionProposalResult:
        generated_at = _utc(as_of or datetime.now(timezone.utc))
        blocked_reasons: list[str] = []

        if not self.config.enabled:
            blocked_reasons.append("options_planner_disabled")

        payload = signal.payload
        source_symbol = payload.symbol.upper()
        symbol = self.config.option_symbol_for(source_symbol)
        if symbol not in self.config.allowed_symbols:
            blocked_reasons.append(f"symbol_not_enabled:{symbol}")

        if signal.decision is not None and signal.decision.status == "blocked":
            blocked_reasons.append("signal_decision_blocked")

        requested_quantity = payload.qty
        if requested_quantity > self.config.max_contracts:
            blocked_reasons.append(f"quantity_exceeds_option_max:{requested_quantity}>{self.config.max_contracts}")

        target_expiries = self._resolve_expiries(generated_at.date())
        if not target_expiries:
            blocked_reasons.append("no_valid_target_expiries")

        if blocked_reasons:
            quote_freshness = self._quote_freshness(chain, generated_at)
            return OptionProposalResult(
                signal_id=signal.id,
                generated_at=generated_at,
                underlying_price=self._planning_underlying_price(
                    source_symbol=source_symbol,
                    option_symbol=symbol,
                    payload_underlying_price=payload.underlying_price,
                    provider_underlying_price=underlying_price,
                ),
                blocked_reasons=list(dict.fromkeys(blocked_reasons)),
                chain_contract_count=len(chain),
                quote_freshness=quote_freshness,
            )

        target_rights = self._target_rights(symbol, payload.direction)
        target_expiry_labels = {expiry: label for expiry, label in target_expiries}
        matching_contracts = [
            contract
            for contract in chain
            if contract.symbol == symbol and contract.right in target_rights and contract.expiry in target_expiry_labels
        ]
        quote_freshness = self._quote_freshness(matching_contracts, generated_at)
        by_expiry_and_right: dict[tuple[date, OptionRight], list[OptionContractSnapshot]] = defaultdict(list)
        for contract in matching_contracts:
            by_expiry_and_right[(contract.expiry, contract.right)].append(contract)

        planning_underlying_price = self._planning_underlying_price(
            source_symbol=source_symbol,
            option_symbol=symbol,
            payload_underlying_price=payload.underlying_price,
            provider_underlying_price=underlying_price,
        )
        proposals: list[OptionProposal] = []
        proposal_filter_reasons: list[str] = []
        candidate_diagnostics: list[OptionCandidateDiagnostic] = []
        eligible_count = 0
        for expiry, label in target_expiries:
            for right in target_rights:
                contracts = sorted(by_expiry_and_right.get((expiry, right), []), key=lambda item: item.strike)
                if not contracts:
                    proposal_filter_reasons.append(f"no_{right.lower()}_contracts_for_expiry:{expiry.isoformat()}")
                    continue

                long_candidates = []
                ineligible_reasons: list[str] = []
                for contract in contracts:
                    contract_reasons = self._long_ineligibility_reasons(
                        contract,
                        label=label,
                        as_of=generated_at,
                        underlying_price=planning_underlying_price,
                    )
                    if contract_reasons:
                        ineligible_reasons.extend(contract_reasons)
                    else:
                        long_candidates.append(contract)
                    candidate_diagnostics.append(_candidate_diagnostic(contract, contract_reasons))
                eligible_count += len(long_candidates)
                if not long_candidates:
                    proposal_filter_reasons.extend(
                        f"{reason}:{expiry.isoformat()}" for reason in dict.fromkeys(ineligible_reasons)
                    )
                    proposal_filter_reasons.append(f"no_eligible_long_contracts:{expiry.isoformat()}")
                    proposal_filter_reasons.append(f"no_eligible_{right.lower()}_long_contracts:{expiry.isoformat()}")
                    continue

                expiry_proposals = []
                primary_contract = self._primary_contract(long_candidates, planning_underlying_price)
                atm_single = None
                if primary_contract is not None:
                    primary_reason = (
                        "itm_primary"
                        if _is_in_the_money(primary_contract, planning_underlying_price)
                        else "atm_primary"
                    )
                    atm_single = self._single_proposal(
                        signal,
                        primary_contract,
                        requested_quantity,
                        generated_at,
                        label,
                        underlying_price=planning_underlying_price,
                        allow_max_loss_override=True,
                        extra_reasons=[primary_reason],
                    )
                    if atm_single is not None:
                        expiry_proposals.append(atm_single)

                for long_contract in long_candidates:
                    if atm_single is None or not _same_contract(long_contract, primary_contract):
                        single = self._single_proposal(
                            signal,
                            long_contract,
                            requested_quantity,
                            generated_at,
                            label,
                            underlying_price=planning_underlying_price,
                        )
                        if single is None:
                            self._append_candidate_reason(candidate_diagnostics, long_contract, "debit_out_of_range")
                            proposal_filter_reasons.append(f"debit_out_of_range:{expiry.isoformat()}")
                        else:
                            expiry_proposals.append(single)
                    spread = self._find_short_spread_leg(long_contract, contracts, as_of=generated_at)
                    if spread is not None:
                        vertical = self._vertical_proposal(
                            signal,
                            long_contract,
                            spread,
                            requested_quantity,
                            generated_at,
                            label,
                            underlying_price=planning_underlying_price,
                        )
                        if vertical is None:
                            self._append_candidate_reason(
                                candidate_diagnostics,
                                long_contract,
                                "spread_debit_out_of_range",
                            )
                            proposal_filter_reasons.append(f"spread_debit_out_of_range:{expiry.isoformat()}")
                        else:
                            expiry_proposals.append(vertical)
                    else:
                        self._append_candidate_reason(candidate_diagnostics, long_contract, "no_spread_leg")
                        proposal_filter_reasons.append(f"no_spread_leg:{expiry.isoformat()}")

                valid_expiry_proposals = [proposal for proposal in expiry_proposals if proposal is not None]
                valid_expiry_proposals.sort(key=self._proposal_sort_key)
                proposals.extend(valid_expiry_proposals[: self.config.max_proposals_per_expiry])

        proposals = self._balanced_proposals(proposals)
        if not proposals:
            blocked_reasons.extend(proposal_filter_reasons)
            blocked_reasons.append("no_proposals_after_filters")

        return OptionProposalResult(
            signal_id=signal.id,
            generated_at=generated_at,
            underlying_price=planning_underlying_price,
            proposals=proposals,
            blocked_reasons=list(dict.fromkeys(blocked_reasons)),
            chain_contract_count=len(chain),
            eligible_contract_count=eligible_count,
            candidate_diagnostics=_rank_candidate_diagnostics(candidate_diagnostics)[:8],
            quote_freshness=quote_freshness,
        )

    def _single_proposal(
        self,
        signal: SignalRecord,
        contract: OptionContractSnapshot,
        requested_quantity: int,
        generated_at: datetime,
        expiry_label: str,
        *,
        underlying_price: float | None = None,
        allow_max_loss_override: bool = False,
        extra_reasons: Sequence[str] | None = None,
    ) -> OptionProposal | None:
        if contract.ask is None:
            return None
        natural_limit_price = round(contract.ask, 2)
        per_contract_debit = round(natural_limit_price * 100, 2)
        quantity = self._quantity_for_debit(per_contract_debit, requested_quantity)
        if quantity is None:
            if not allow_max_loss_override:
                return None
            quantity = max(1, min(requested_quantity, self.config.max_contracts))
        send_limit_price = self._send_limit_price(contract.symbol, natural_limit_price, quantity)
        if send_limit_price is None:
            if not allow_max_loss_override:
                return None
            send_limit_price = self._uncapped_send_limit_price(contract.symbol, natural_limit_price)
        natural_debit = round(per_contract_debit * quantity, 2)
        debit = round(send_limit_price * 100 * quantity, 2)

        leg = _proposal_leg("BUY", contract, quantity, contract.ask)
        score = self._score([contract], debit=debit, expiry_label=expiry_label)
        price_protection = self._price_protection_note(contract.symbol, natural_limit_price, send_limit_price)
        reasons = ["dry_run_proposal", "single_long_option", *(extra_reasons or [])]
        if allow_max_loss_override and debit > self.config.max_debit_per_trade:
            reasons.append("max_loss_override")
            primary_label = "ITM" if "itm_primary" in reasons else "ATM"
            price_protection = (
                f"{price_protection} {primary_label} proposal included above max loss by operator request."
            )
        tos_order_line = _tos_order_line(
            symbol=contract.symbol,
            structure="SINGLE",
            quantity=quantity,
            expiry=contract.expiry,
            strikes=[contract.strike],
            right=contract.right,
            limit_price=send_limit_price,
        )
        return OptionProposal(
            id=self._proposal_id(signal.id, "single", [contract]),
            signal_id=signal.id,
            symbol=contract.symbol,
            direction=_direction_for_right(contract.right),
            structure="single",
            created_at=generated_at,
            expiry=contract.expiry,
            quantity=quantity,
            underlying_price=underlying_price,
            legs=[leg],
            debit=debit,
            max_loss=debit,
            natural_limit_price=natural_limit_price,
            natural_debit=natural_debit,
            send_limit_price=send_limit_price,
            price_protection=price_protection,
            net_delta=_net_delta([("BUY", contract)], quantity),
            score=score,
            tos_order_line=tos_order_line,
            exit_targets=self._exit_targets(
                signal,
                quantity,
                send_limit_price,
                symbol=contract.symbol,
                structure="SINGLE",
                expiry=contract.expiry,
                strikes=[contract.strike],
                right=contract.right,
            ),
            reasons=list(dict.fromkeys(reasons)),
            notes=self._contract_notes([contract]),
        )

    def _target_rights(self, symbol: str, direction: Direction) -> list[OptionRight]:
        configured = self.config.proposal_rights_by_symbol.get(symbol.upper())
        if configured:
            return [right for right in configured if right in {"CALL", "PUT"}]
        return [_right_for_direction(direction)]

    def _planning_underlying_price(
        self,
        *,
        source_symbol: str,
        option_symbol: str,
        payload_underlying_price: float | None,
        provider_underlying_price: float | None,
    ) -> float | None:
        if provider_underlying_price is not None:
            return provider_underlying_price
        if source_symbol == option_symbol:
            return payload_underlying_price
        return None

    def _vertical_proposal(
        self,
        signal: SignalRecord,
        long_contract: OptionContractSnapshot,
        short_contract: OptionContractSnapshot,
        requested_quantity: int,
        generated_at: datetime,
        expiry_label: str,
        *,
        underlying_price: float | None = None,
    ) -> OptionProposal | None:
        if long_contract.ask is None or short_contract.bid is None:
            return None
        natural_limit_price = round(long_contract.ask - short_contract.bid, 2)
        if natural_limit_price <= 0:
            return None
        per_contract_debit_dollars = round(natural_limit_price * 100, 2)
        quantity = self._quantity_for_debit(per_contract_debit_dollars, requested_quantity)
        if quantity is None:
            return None
        send_limit_price = self._send_limit_price(long_contract.symbol, natural_limit_price, quantity)
        if send_limit_price is None:
            return None
        natural_debit = round(per_contract_debit_dollars * quantity, 2)
        debit = round(send_limit_price * 100 * quantity, 2)
        width = abs(short_contract.strike - long_contract.strike)
        if debit >= width * 100 * quantity:
            return None

        legs = [
            _proposal_leg("BUY", long_contract, quantity, long_contract.ask),
            _proposal_leg("SELL", short_contract, quantity, short_contract.bid),
        ]
        score = self._score([long_contract, short_contract], debit=debit, expiry_label=expiry_label)
        tos_order_line = _tos_order_line(
            symbol=long_contract.symbol,
            structure="VERTICAL",
            quantity=quantity,
            expiry=long_contract.expiry,
            strikes=[long_contract.strike, short_contract.strike],
            right=long_contract.right,
            limit_price=send_limit_price,
        )
        return OptionProposal(
            id=self._proposal_id(signal.id, "debit_vertical", [long_contract, short_contract]),
            signal_id=signal.id,
            symbol=long_contract.symbol,
            direction=_direction_for_right(long_contract.right),
            structure="debit_vertical",
            created_at=generated_at,
            expiry=long_contract.expiry,
            quantity=quantity,
            underlying_price=underlying_price,
            legs=legs,
            debit=debit,
            max_loss=debit,
            natural_limit_price=natural_limit_price,
            natural_debit=natural_debit,
            send_limit_price=send_limit_price,
            price_protection=self._price_protection_note(
                long_contract.symbol,
                natural_limit_price,
                send_limit_price,
            ),
            width=width,
            net_delta=_net_delta([("BUY", long_contract), ("SELL", short_contract)], quantity),
            score=score,
            tos_order_line=tos_order_line,
            exit_targets=self._exit_targets(
                signal,
                quantity,
                send_limit_price,
                symbol=long_contract.symbol,
                structure="VERTICAL",
                expiry=long_contract.expiry,
                strikes=[long_contract.strike, short_contract.strike],
                right=long_contract.right,
                max_target_price=width,
            ),
            reasons=["dry_run_proposal", "debit_vertical"],
            notes=self._contract_notes([long_contract, short_contract]),
        )

    def _is_eligible_long(
        self,
        contract: OptionContractSnapshot,
        label: str,
        as_of: datetime,
        underlying_price: float | None,
    ) -> bool:
        return not self._long_ineligibility_reasons(
            contract,
            label=label,
            as_of=as_of,
            underlying_price=underlying_price,
        )

    def _long_ineligibility_reasons(
        self,
        contract: OptionContractSnapshot,
        label: str,
        as_of: datetime,
        underlying_price: float | None,
    ) -> list[str]:
        reasons: list[str] = []
        if not self.config.allow_in_the_money_primary:
            reasons.extend(_moneyness_reasons(contract, underlying_price))
        if not self._has_usable_market(contract):
            reasons.append("invalid_bid_ask")
        else:
            reasons.extend(self._liquidity_reasons(contract))
        if self._is_stale(contract, as_of):
            reasons.append("stale_quote")
        if contract.delta is None:
            reasons.append("missing_delta")
            return reasons
        low, high = self._delta_band(label)
        if not low <= abs(contract.delta) <= high:
            reasons.append("delta_out_of_range")
        return reasons

    def _is_eligible_short(self, contract: OptionContractSnapshot, as_of: datetime) -> bool:
        return (
            self._has_usable_market(contract)
            and not self._is_stale(contract, as_of)
            and self._has_acceptable_liquidity(contract)
        )

    def _find_short_spread_leg(
        self,
        long_contract: OptionContractSnapshot,
        contracts: Sequence[OptionContractSnapshot],
        as_of: datetime,
    ) -> OptionContractSnapshot | None:
        target_strike = (
            long_contract.strike + self.config.spread_width_points
            if long_contract.right == "CALL"
            else long_contract.strike - self.config.spread_width_points
        )
        for contract in contracts:
            if abs(contract.strike - target_strike) < 0.0001 and self._is_eligible_short(contract, as_of):
                return contract
        return None

    def _has_usable_market(self, contract: OptionContractSnapshot) -> bool:
        if contract.bid is None or contract.ask is None:
            return False
        if contract.ask <= 0 or contract.bid < 0 or contract.ask < contract.bid:
            return False
        return True

    def _has_acceptable_liquidity(self, contract: OptionContractSnapshot) -> bool:
        return not self._liquidity_reasons(contract)

    def _liquidity_reasons(self, contract: OptionContractSnapshot) -> list[str]:
        reasons: list[str] = []
        if contract.mark is None or contract.mark <= 0:
            reference = ((contract.bid or 0) + (contract.ask or 0)) / 2
        else:
            reference = contract.mark
        if reference <= 0:
            return ["invalid_market_reference"]
        spread_percent = ((contract.ask or 0) - (contract.bid or 0)) / reference * 100
        if spread_percent > self.config.max_bid_ask_spread_percent:
            reasons.append("wide_bid_ask_spread")
        if contract.open_interest is not None and contract.open_interest < self.config.min_open_interest:
            reasons.append("open_interest_below_min")
        return reasons

    def _is_stale(self, contract: OptionContractSnapshot, as_of: datetime) -> bool:
        if self.config.quote_stale_after_seconds == 0:
            return False
        age_seconds = (as_of - _utc(contract.timestamp)).total_seconds()
        return age_seconds > self.config.quote_stale_after_seconds

    def _quote_freshness(
        self,
        contracts: Sequence[OptionContractSnapshot],
        as_of: datetime,
    ) -> OptionQuoteFreshness:
        if not contracts:
            return OptionQuoteFreshness(stale_after_seconds=self.config.quote_stale_after_seconds)
        freshest_quote_time = max(_utc(contract.timestamp) for contract in contracts)
        freshest_quote_age_seconds = max(0.0, (as_of - freshest_quote_time).total_seconds())
        stale_count = sum(1 for contract in contracts if self._is_stale(contract, as_of))
        if stale_count == 0:
            status = "fresh"
        elif stale_count == len(contracts):
            status = "stale"
        else:
            status = "mixed"
        return OptionQuoteFreshness(
            status=status,
            checked_contract_count=len(contracts),
            stale_contract_count=stale_count,
            stale_after_seconds=self.config.quote_stale_after_seconds,
            freshest_quote_time=freshest_quote_time,
            freshest_quote_age_seconds=round(freshest_quote_age_seconds, 3),
        )

    def _delta_band(self, label: str) -> tuple[float, float]:
        band = self.config.target_delta_long.get(label.upper(), [0.35, 0.60])
        low, high = sorted(float(item) for item in band)
        return low, high

    def _score(self, contracts: Sequence[OptionContractSnapshot], debit: float, expiry_label: str) -> float:
        long_contract = contracts[0]
        low, high = self._delta_band(expiry_label)
        target_delta = (low + high) / 2
        delta_score = max(0.0, 40 - abs(abs(long_contract.delta or 0) - target_delta) * 100)
        spread_scores = []
        for contract in contracts:
            reference = contract.mark or ((contract.bid or 0) + (contract.ask or 0)) / 2
            spread_scores.append(0 if reference <= 0 else max(0.0, 30 - (((contract.ask or 0) - (contract.bid or 0)) / reference * 100)))
        liquidity_score = sum(spread_scores) / len(spread_scores) if spread_scores else 0
        open_interest_values = [contract.open_interest for contract in contracts if contract.open_interest is not None]
        oi_score = min(15.0, (min(open_interest_values) / 100) if open_interest_values else 5.0)
        debit_span = max(self.config.max_debit_per_trade - self.config.min_debit_per_trade, 1)
        debit_score = max(0.0, 15 - ((debit - self.config.min_debit_per_trade) / debit_span * 10))
        return round(delta_score + liquidity_score + oi_score + debit_score, 4)

    def _debit_in_range(self, debit: float) -> bool:
        return self.config.min_debit_per_trade <= debit <= self.config.max_debit_per_trade

    def _send_limit_price(self, symbol: str, natural_limit_price: float, quantity: int) -> float | None:
        if natural_limit_price <= 0 or quantity <= 0:
            return None
        target = natural_limit_price
        if symbol.upper() in self.config.marketable_limit_symbols:
            target = round(natural_limit_price + self.config.marketable_limit_offset, 2)
        max_per_contract = self.config.max_debit_per_trade / (quantity * 100)
        target = round(min(target, max_per_contract), 2)
        if target + 0.0001 < natural_limit_price:
            return None
        return target

    def _uncapped_send_limit_price(self, symbol: str, natural_limit_price: float) -> float:
        if symbol.upper() in self.config.marketable_limit_symbols:
            return round(natural_limit_price + self.config.marketable_limit_offset, 2)
        return round(natural_limit_price, 2)

    def _price_protection_note(self, symbol: str, natural_limit_price: float, send_limit_price: float) -> str:
        if symbol.upper() not in self.config.marketable_limit_symbols:
            return "Limit at proposal debit."
        intended = round(natural_limit_price + self.config.marketable_limit_offset, 2)
        if send_limit_price + 0.0001 < intended:
            return (
                f"Marketable limit capped by max loss: natural {natural_limit_price:.2f}, "
                f"send {send_limit_price:.2f}."
            )
        return f"Marketable limit: natural {natural_limit_price:.2f} + {self.config.marketable_limit_offset:.2f}."

    def _exit_targets(
        self,
        signal: SignalRecord,
        quantity: int,
        send_limit_price: float,
        *,
        symbol: str,
        structure: str,
        expiry: date,
        strikes: Sequence[float],
        right: OptionRight,
        max_target_price: float | None = None,
    ) -> list[OptionProposalExitTarget]:
        if quantity <= 0 or send_limit_price <= 0:
            return []
        target_percentages = (
            self.config.exit_target_percentages
            or signal.payload.profit_target_percentages
            or _default_exit_target_percentages(quantity)
        )
        targets: list[OptionProposalExitTarget] = []
        for target_qty, target_percent in _exit_target_allocations(quantity, target_percentages):
            uncapped_target = round(send_limit_price * (1 + (target_percent / 100)), 2)
            target_limit_price = uncapped_target
            note = ""
            if max_target_price is not None and target_limit_price > max_target_price:
                target_limit_price = round(max_target_price, 2)
                note = "capped at spread width"
            estimated_profit = round(max(0.0, (target_limit_price - send_limit_price) * 100 * target_qty), 2)
            targets.append(
                OptionProposalExitTarget(
                    qty=target_qty,
                    target_percent=round(float(target_percent), 4),
                    entry_limit_price=round(send_limit_price, 2),
                    target_limit_price=target_limit_price,
                    estimated_profit=estimated_profit,
                    tos_exit_order_line=_tos_exit_order_line(
                        symbol=symbol,
                        structure=structure,
                        quantity=target_qty,
                        expiry=expiry,
                        strikes=strikes,
                        right=right,
                        limit_price=target_limit_price,
                    ),
                    note=note,
                )
            )
        return targets

    def _quantity_for_debit(self, per_contract_debit: float, requested_quantity: int) -> int | None:
        if per_contract_debit <= 0:
            return None
        quantity = max(requested_quantity, math.ceil(self.config.min_debit_per_trade / per_contract_debit))
        if quantity > self.config.max_contracts:
            return None
        debit = round(per_contract_debit * quantity, 2)
        return quantity if self._debit_in_range(debit) else None

    def _proposal_sort_key(self, proposal: OptionProposal) -> tuple[int, float, date, float, str]:
        atm_rank = 0 if "atm_primary" in proposal.reasons or "itm_primary" in proposal.reasons else 1
        return (atm_rank, -proposal.score, proposal.expiry, proposal.debit, proposal.id)

    def _balanced_proposals(self, proposals: Sequence[OptionProposal]) -> list[OptionProposal]:
        ranked = sorted(proposals, key=self._proposal_sort_key)
        selected: list[OptionProposal] = []
        selected_ids: set[str] = set()

        def add(proposal: OptionProposal) -> None:
            if proposal.id in selected_ids or len(selected) >= self.config.max_proposals_total:
                return
            selected.append(proposal)
            selected_ids.add(proposal.id)

        structure_limits = [
            ("single", self.config.max_single_proposals_total),
            ("debit_vertical", self.config.max_spread_proposals_total),
        ]
        for structure, limit in structure_limits:
            if limit <= 0:
                continue
            added_for_structure = 0
            for right in ("CALL", "PUT"):
                if added_for_structure >= limit:
                    break
                proposal = next(
                    (
                        item
                        for item in ranked
                        if item.structure == structure
                        and item.id not in selected_ids
                        and _primary_right(item) == right
                    ),
                    None,
                )
                if proposal is not None:
                    add(proposal)
                    added_for_structure += 1

            if added_for_structure < limit:
                for proposal in ranked:
                    if added_for_structure >= limit or len(selected) >= self.config.max_proposals_total:
                        break
                    if proposal.structure == structure and proposal.id not in selected_ids:
                        add(proposal)
                        added_for_structure += 1

        for proposal in ranked:
            if len(selected) >= self.config.max_proposals_total:
                break
            add(proposal)
        return selected

    def _primary_contract(
        self,
        contracts: Sequence[OptionContractSnapshot],
        underlying_price: float | None,
    ) -> OptionContractSnapshot | None:
        if not contracts:
            return None
        if underlying_price is None:
            return contracts[0]
        primary_right = contracts[0].right
        if self.config.allow_in_the_money_primary:
            if primary_right == "CALL":
                itm = [contract for contract in contracts if contract.strike < underlying_price - 0.0001]
                if itm:
                    return min(itm, key=lambda contract: (abs(contract.strike - underlying_price), -contract.strike))
            else:
                itm = [contract for contract in contracts if contract.strike > underlying_price + 0.0001]
                if itm:
                    return min(itm, key=lambda contract: (abs(contract.strike - underlying_price), contract.strike))
        if primary_right == "CALL":
            atm_otm = [contract for contract in contracts if contract.strike + 0.0001 >= underlying_price]
            candidates = atm_otm or list(contracts)
            return min(candidates, key=lambda contract: (abs(contract.strike - underlying_price), contract.strike))
        atm_otm = [contract for contract in contracts if contract.strike <= underlying_price + 0.0001]
        candidates = atm_otm or list(contracts)
        return min(candidates, key=lambda contract: (abs(contract.strike - underlying_price), -contract.strike))

    def _append_candidate_reason(
        self,
        diagnostics: list[OptionCandidateDiagnostic],
        contract: OptionContractSnapshot,
        reason: str,
    ) -> None:
        for diagnostic in diagnostics:
            if (
                diagnostic.expiry == contract.expiry
                and abs(diagnostic.strike - contract.strike) < 0.0001
                and diagnostic.right == contract.right
            ):
                existing = [item for item in diagnostic.reasons if item != "passed_long_filters"]
                diagnostic.reasons = list(dict.fromkeys([*existing, reason]))
                return
        diagnostics.append(_candidate_diagnostic(contract, [reason]))

    def _contract_notes(self, contracts: Iterable[OptionContractSnapshot]) -> list[str]:
        notes: list[str] = []
        for contract in contracts:
            if contract.delta is None:
                notes.append("delta_missing")
            if contract.open_interest is None:
                notes.append("open_interest_missing")
        return list(dict.fromkeys(notes))

    def _resolve_expiries(self, as_of_date: date) -> list[tuple[date, str]]:
        resolved: list[tuple[date, str]] = []
        for label in self.config.expiries:
            expiry = _resolve_expiry_label(label, as_of_date)
            if expiry is not None:
                resolved.append((expiry, label.upper()))
        return resolved

    def _proposal_id(
        self,
        signal_id: str,
        structure: str,
        contracts: Sequence[OptionContractSnapshot],
    ) -> str:
        parts = [signal_id, structure]
        parts.extend(
            f"{contract.symbol}:{contract.expiry.isoformat()}:{contract.strike:g}:{contract.right}"
            for contract in contracts
        )
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
        return f"prop_{digest}"


def _right_for_direction(direction: Direction) -> OptionRight:
    return "CALL" if direction == "long" else "PUT"


def _direction_for_right(right: OptionRight) -> Direction:
    return "long" if right == "CALL" else "short"


def _primary_right(proposal: OptionProposal) -> OptionRight | None:
    for leg in proposal.legs:
        if leg.action == "BUY":
            return leg.right
    return proposal.legs[0].right if proposal.legs else None


def _same_contract(
    left: OptionContractSnapshot,
    right: OptionContractSnapshot | None,
) -> bool:
    if right is None:
        return False
    return (
        left.symbol == right.symbol
        and left.expiry == right.expiry
        and abs(left.strike - right.strike) < 0.0001
        and left.right == right.right
    )


def _default_exit_target_percentages(quantity: int) -> list[float]:
    if quantity <= 1:
        return [20.0]
    if quantity == 2:
        return [20.0, 40.0]
    return [20.0, 40.0, 50.0]


def _exit_target_allocations(quantity: int, percentages: Sequence[float]) -> list[tuple[int, float]]:
    clean_percentages = [float(percent) for percent in percentages if float(percent) > 0]
    if not clean_percentages:
        clean_percentages = _default_exit_target_percentages(quantity)

    allocations: list[tuple[int, float]] = []
    remaining = quantity
    for index, percent in enumerate(clean_percentages):
        if remaining <= 0:
            break
        target_qty = remaining if index == len(clean_percentages) - 1 else 1
        allocations.append((target_qty, percent))
        remaining -= target_qty
    return allocations


def _moneyness_reasons(contract: OptionContractSnapshot, underlying_price: float | None) -> list[str]:
    if underlying_price is None:
        return ["missing_underlying_price"]
    if _is_in_the_money(contract, underlying_price):
        return ["in_the_money_long_contract"]
    return []


def _is_in_the_money(contract: OptionContractSnapshot, underlying_price: float | None) -> bool:
    if underlying_price is None:
        return False
    if contract.right == "CALL":
        return contract.strike < underlying_price
    if contract.right == "PUT":
        return contract.strike > underlying_price
    return False


def _proposal_leg(
    action: ProposalLegAction,
    contract: OptionContractSnapshot,
    qty: int,
    price: float,
) -> OptionProposalLeg:
    return OptionProposalLeg(
        action=action,
        qty=qty,
        symbol=contract.symbol,
        broker_symbol=contract.broker_symbol,
        expiry=contract.expiry,
        strike=contract.strike,
        right=contract.right,
        price=round(price, 2),
        bid=contract.bid,
        ask=contract.ask,
        mark=contract.mark,
        delta=contract.delta,
        open_interest=contract.open_interest,
        volume=contract.volume,
    )


def _net_delta(legs: Sequence[tuple[str, OptionContractSnapshot]], quantity: int) -> float | None:
    if not any(contract.delta is not None for _, contract in legs):
        return None
    total = 0.0
    for action, contract in legs:
        multiplier = 1 if action == "BUY" else -1
        total += (contract.delta or 0.0) * multiplier * quantity
    return round(total, 4)


def _tos_order_line(
    symbol: str,
    structure: str,
    quantity: int,
    expiry: date,
    strikes: Sequence[float],
    right: OptionRight,
    limit_price: float,
) -> str:
    strike_text = "/".join(_format_strike(strike) for strike in strikes)
    return (
        f"BUY +{quantity} {structure} {symbol.upper()} 100 "
        f"{_format_tos_expiry(expiry)} {strike_text} {right} @{limit_price:.2f} LMT"
    )


def _tos_exit_order_line(
    symbol: str,
    structure: str,
    quantity: int,
    expiry: date,
    strikes: Sequence[float],
    right: OptionRight,
    limit_price: float,
) -> str:
    strike_text = "/".join(_format_strike(strike) for strike in strikes)
    return (
        f"SELL -{quantity} {structure} {symbol.upper()} 100 "
        f"{_format_tos_expiry(expiry)} {strike_text} {right} @{limit_price:.2f} LMT GTC"
    )


def _format_tos_expiry(expiry: date) -> str:
    return expiry.strftime("%d %b %y").upper()


def _format_strike(strike: float) -> str:
    return str(int(strike)) if float(strike).is_integer() else str(strike)


def _candidate_diagnostic(
    contract: OptionContractSnapshot,
    reasons: Sequence[str],
) -> OptionCandidateDiagnostic:
    return OptionCandidateDiagnostic(
        expiry=contract.expiry,
        strike=contract.strike,
        right=contract.right,
        bid=contract.bid,
        ask=contract.ask,
        mark=contract.mark,
        delta=contract.delta,
        open_interest=contract.open_interest,
        volume=contract.volume,
        quote_time=contract.timestamp,
        reasons=list(dict.fromkeys(reasons)) or ["passed_long_filters"],
    )


def _rank_candidate_diagnostics(
    diagnostics: Sequence[OptionCandidateDiagnostic],
) -> list[OptionCandidateDiagnostic]:
    def key(diagnostic: OptionCandidateDiagnostic) -> tuple[int, float, float, float]:
        delta_distance = abs(abs(diagnostic.delta or 0.0) - 0.5) if diagnostic.delta is not None else 9.0
        spread = (diagnostic.ask or 0.0) - (diagnostic.bid or 0.0)
        open_interest_score = -(diagnostic.open_interest or 0)
        return (len(diagnostic.reasons), delta_distance, spread, open_interest_score)

    return sorted(diagnostics, key=key)


def _resolve_expiry_label(label: str, as_of_date: date) -> date | None:
    normalized = label.upper().strip()
    match = re.fullmatch(r"(\d+)DTE", normalized)
    if match:
        return _add_business_days(as_of_date, int(match.group(1)))
    if normalized in {"THIS_FRIDAY", "THIS FRIDAY"}:
        return _friday_for_week(as_of_date)
    if normalized in {"NEXT_WEEK_FRIDAY", "NEXT WEEK FRIDAY", "NEXT_FRIDAY"}:
        return _friday_for_week(as_of_date) + timedelta(days=7)
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _friday_for_week(as_of_date: date) -> date:
    days_until_friday = (4 - as_of_date.weekday()) % 7
    return as_of_date + timedelta(days=days_until_friday)


def _add_business_days(as_of_date: date, days: int) -> date:
    if days <= 0:
        return as_of_date
    current = as_of_date
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
