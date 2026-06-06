"""Signal decision gate for dashboard review and future Schwab routing."""

from __future__ import annotations

from nt_schwab_bridge.config import BridgeConfig, IndicatorSourceConfig
from nt_schwab_bridge.models import SignalDecision, SignalPayload


class SignalDecisionEngine:
    """Evaluate normalized signals without placing or previewing orders."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._sources = {self._key(source.name): source for source in config.indicators.sources}

    def evaluate(self, payload: SignalPayload) -> SignalDecision:
        reasons: list[str] = []
        blocked = False

        indicator_source = self._indicator_source(payload)
        source_config = self._source_config(indicator_source)
        if self.config.risk.enabled:
            blocked = self._evaluate_risk(payload, reasons)

        source_blocked = self._evaluate_indicator_source(payload, indicator_source, source_config, reasons)
        blocked = blocked or source_blocked

        if blocked:
            status = "blocked"
            route = "none"
        elif self._can_route_to_live_order():
            status = "ready"
            route = "schwab_order"
        elif self._can_route_to_preview():
            status = "ready"
            route = "schwab_preview"
        else:
            status = "review_required"
            route = "dashboard_review"
            if self.config.risk.require_manual_review:
                reasons.append("manual_review_required")
            if not self.config.risk.trading_enabled:
                reasons.append("trading_disabled")

        return SignalDecision(
            status=status,
            route=route,
            reasons=list(dict.fromkeys(reasons)),
            target_dollars=self.config.risk.default_target_dollars,
            stop_loss_dollars=self.config.risk.default_stop_loss_dollars,
            execution_mode=self.config.service.execution_mode,
            allow_live_orders=self.config.service.allow_live_orders,
            indicator_source=indicator_source,
            notes="Decision only; no Schwab order is placed by this phase.",
        )

    def _evaluate_risk(self, payload: SignalPayload, reasons: list[str]) -> bool:
        blocked = False

        if payload.qty > self.config.risk.max_quantity:
            blocked = True
            reasons.append(f"quantity_exceeds_max:{payload.qty}>{self.config.risk.max_quantity}")

        if payload.direction not in self.config.risk.allowed_directions:
            blocked = True
            reasons.append(f"direction_not_allowed:{payload.direction}")

        if self.config.risk.require_underlying_price and payload.underlying_price is None:
            blocked = True
            reasons.append("underlying_price_required")

        return blocked

    def _evaluate_indicator_source(
        self,
        payload: SignalPayload,
        indicator_source: str | None,
        source_config: IndicatorSourceConfig | None,
        reasons: list[str],
    ) -> bool:
        blocked = False

        if not indicator_source:
            if self.config.indicators.require_configured_source:
                reasons.append("indicator_source_required")
                return True
            return False

        if source_config is None:
            if self.config.indicators.require_configured_source:
                reasons.append(f"indicator_source_not_configured:{indicator_source}")
                blocked = True
            return blocked

        if not source_config.enabled:
            reasons.append(f"indicator_source_disabled:{indicator_source}")
            blocked = True

        if source_config.signal_types and payload.signal_type not in source_config.signal_types:
            reasons.append(f"signal_type_not_allowed_for_source:{payload.signal_type}")
            blocked = True

        return blocked

    def _can_route_to_live_order(self) -> bool:
        return (
            self.config.risk.trading_enabled
            and not self.config.risk.require_manual_review
            and self.config.service.execution_mode == "live"
            and self.config.service.allow_live_orders
        )

    def _can_route_to_preview(self) -> bool:
        return self.config.risk.trading_enabled and not self.config.risk.require_manual_review

    def _source_config(self, indicator_source: str | None) -> IndicatorSourceConfig | None:
        if not indicator_source:
            return None
        return self._sources.get(self._key(indicator_source))

    def _indicator_source(self, payload: SignalPayload) -> str | None:
        source = payload.source_indicator or (payload.indicator.name if payload.indicator else None)
        return source.strip() if source and source.strip() else None

    def _key(self, value: str) -> str:
        return value.casefold().strip()
