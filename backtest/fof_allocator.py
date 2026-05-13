"""
FOF Allocator
=============

Meta-allocation logic for combining multiple personality sleeves into a
single fund-of-funds portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SleeveSnapshot:
    """Serializable sleeve snapshot used by the FOF allocator."""

    personality: str
    target_weights: Dict[str, float]
    metrics: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FOFAllocationResult:
    """Output produced by the FOF allocator."""

    sleeve_weights: Dict[str, float]
    final_stock_weights: Dict[str, float]
    rationale: str
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class FOFAllocator:
    """Rule-based meta allocator that combines multiple personality sleeves."""

    DEFAULT_CONFIG: Dict[str, Any] = {
        "base_weights": {
            "conservative": 0.20,
            "balanced": 0.40,
            "aggressive": 0.10,
            "passive": 0.30,
        },
        "max_sleeve_weight": 0.40,
        "min_passive_weight": 0.20,
        "active_weight_limit": 0.70,
        "max_single_stock_weight": 0.15,
        "regime_tilt": 0.10,
    }
    PASSIVE_SLEEVES = {"passive", "equal_weight_index", "equal_weight", "ewi"}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = self._merge_config(config or {})

    def allocate(
        self,
        sleeves: Dict[str, SleeveSnapshot],
        market_context: Optional[Dict[str, Any]] = None,
    ) -> FOFAllocationResult:
        """Allocate across sleeve snapshots and aggregate final stock weights."""
        available_sleeves = {
            name: snapshot for name, snapshot in (sleeves or {}).items() if snapshot.target_weights
        }
        if not available_sleeves:
            raise ValueError("FOF allocation requires at least one sleeve with target weights")

        regime = self._resolve_regime(available_sleeves, market_context or {})
        sleeve_weights = self._build_initial_weights(available_sleeves)
        sleeve_weights = self._apply_regime_tilt(sleeve_weights, regime)
        sleeve_weights = self._enforce_sleeve_constraints(sleeve_weights)
        final_stock_weights = self._aggregate_stock_weights(available_sleeves, sleeve_weights)
        final_stock_weights = self._cap_single_stock_weights(final_stock_weights)

        rationale = (
            f"FOF meta allocation using {len(available_sleeves)} sleeves under {regime} regime. "
            f"Weights: {', '.join(f'{k}={v:.0%}' for k, v in sorted(sleeve_weights.items()))}."
        )
        diagnostics = {
            "regime": regime,
            "available_sleeves": list(sorted(available_sleeves.keys())),
            "market_context": dict(market_context or {}),
        }
        return FOFAllocationResult(
            sleeve_weights=sleeve_weights,
            final_stock_weights=final_stock_weights,
            rationale=rationale,
            diagnostics=diagnostics,
        )

    def _merge_config(self, override: Dict[str, Any]) -> Dict[str, Any]:
        config = {
            **self.DEFAULT_CONFIG,
            "base_weights": dict(self.DEFAULT_CONFIG["base_weights"]),
        }
        for key, value in override.items():
            if key == "base_weights" and isinstance(value, dict):
                config["base_weights"].update(value)
            else:
                config[key] = value
        return config

    def _build_initial_weights(self, sleeves: Dict[str, SleeveSnapshot]) -> Dict[str, float]:
        base_weights = self.config["base_weights"]
        weights = {name: max(float(base_weights.get(name, 0.0)), 0.0) for name in sleeves}
        if sum(weights.values()) <= 0:
            equal_weight = 1.0 / len(sleeves)
            return {name: equal_weight for name in sleeves}
        return self._normalize(weights)

    def _resolve_regime(self, sleeves: Dict[str, SleeveSnapshot], market_context: Dict[str, Any]) -> str:
        explicit_regime = str(market_context.get("regime", "")).strip().lower()
        if explicit_regime in {"bull", "bear", "neutral", "volatile"}:
            return explicit_regime

        signal_bias = float(market_context.get("signal_bias", 0.0))
        avg_consistency = float(market_context.get("avg_signal_consistency", 0.5))

        if signal_bias >= 0.20:
            return "bull"
        if signal_bias <= -0.20:
            return "bear"
        if avg_consistency < 0.45:
            return "volatile"

        aggressive_exposure = sleeves.get(
            "aggressive", SleeveSnapshot("aggressive", {})
        ).metrics.get("gross_exposure", 0.0)
        conservative_exposure = sleeves.get(
            "conservative", SleeveSnapshot("conservative", {})
        ).metrics.get("gross_exposure", 0.0)
        if aggressive_exposure > conservative_exposure + 0.20:
            return "bull"
        return "neutral"

    def _apply_regime_tilt(self, weights: Dict[str, float], regime: str) -> Dict[str, float]:
        tilt = float(self.config.get("regime_tilt", 0.10))
        adjusted = dict(weights)
        if regime == "bull":
            adjusted["aggressive"] = adjusted.get("aggressive", 0.0) + tilt
            adjusted["conservative"] = adjusted.get("conservative", 0.0) - tilt / 2
            adjusted["passive"] = adjusted.get("passive", 0.0) - tilt / 2
        elif regime == "bear":
            adjusted["conservative"] = adjusted.get("conservative", 0.0) + tilt
            adjusted["passive"] = adjusted.get("passive", 0.0) + tilt / 2
            adjusted["aggressive"] = adjusted.get("aggressive", 0.0) - tilt * 1.5
        elif regime == "volatile":
            adjusted["passive"] = adjusted.get("passive", 0.0) + tilt / 2
            adjusted["balanced"] = adjusted.get("balanced", 0.0) + tilt / 2
            adjusted["aggressive"] = adjusted.get("aggressive", 0.0) - tilt
        return self._normalize({key: max(value, 0.0) for key, value in adjusted.items()})

    def _enforce_sleeve_constraints(self, weights: Dict[str, float]) -> Dict[str, float]:
        max_weight = float(self.config.get("max_sleeve_weight", 0.40))
        min_passive = float(self.config.get("min_passive_weight", 0.20))
        active_limit = float(self.config.get("active_weight_limit", 0.70))

        capped = self._cap_weights(weights, max_weight)
        passive_names = [name for name in capped if name in self.PASSIVE_SLEEVES]
        passive_total = sum(capped[name] for name in passive_names)

        if passive_names and passive_total < min_passive:
            deficit = min_passive - passive_total
            active_names = [name for name in capped if name not in passive_names]
            active_total = sum(capped[name] for name in active_names)
            if active_total > 0:
                scale = max((active_total - deficit) / active_total, 0.0)
                for name in active_names:
                    capped[name] *= scale
                per_passive_boost = deficit / len(passive_names)
                for name in passive_names:
                    capped[name] += per_passive_boost

        active_names = [name for name in capped if name not in passive_names]
        active_total = sum(capped[name] for name in active_names)
        if active_names and active_total > active_limit:
            excess = active_total - active_limit
            scale = max((active_total - excess) / active_total, 0.0)
            for name in active_names:
                capped[name] *= scale
            if passive_names:
                per_passive_boost = excess / len(passive_names)
                for name in passive_names:
                    capped[name] += per_passive_boost

        return self._normalize(capped)

    def _aggregate_stock_weights(
        self,
        sleeves: Dict[str, SleeveSnapshot],
        sleeve_weights: Dict[str, float],
    ) -> Dict[str, float]:
        aggregate: Dict[str, float] = {}
        for sleeve_name, sleeve_weight in sleeve_weights.items():
            snapshot = sleeves.get(sleeve_name)
            if snapshot is None:
                continue
            for ticker, target_weight in snapshot.target_weights.items():
                aggregate[ticker] = aggregate.get(ticker, 0.0) + sleeve_weight * max(float(target_weight), 0.0)
        return self._normalize(aggregate, allow_underweight=True)

    def _cap_single_stock_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        max_stock_weight = float(self.config.get("max_single_stock_weight", 0.15))
        capped = {ticker: min(weight, max_stock_weight) for ticker, weight in weights.items()}
        return self._normalize(capped, allow_underweight=True)

    @staticmethod
    def _cap_weights(weights: Dict[str, float], max_weight: float) -> Dict[str, float]:
        capped = dict(weights)
        for _ in range(len(capped) + 2):
            over = {name: value for name, value in capped.items() if value > max_weight}
            if not over:
                break
            excess = sum(value - max_weight for value in over.values())
            for name in over:
                capped[name] = max_weight
            under_names = [name for name, value in capped.items() if value < max_weight]
            under_total = sum(capped[name] for name in under_names)
            if under_total <= 0 or excess <= 0:
                break
            for name in under_names:
                capped[name] += excess * (capped[name] / under_total)
        return capped

    @staticmethod
    def _normalize(weights: Dict[str, float], allow_underweight: bool = False) -> Dict[str, float]:
        positive = {key: max(float(value), 0.0) for key, value in weights.items()}
        total = sum(positive.values())
        if total <= 0:
            if not positive:
                return {}
            equal = 0.0 if allow_underweight else 1.0 / len(positive)
            return {key: equal for key in positive}
        if allow_underweight and total <= 1.0:
            return positive
        return {key: value / total for key, value in positive.items()}
