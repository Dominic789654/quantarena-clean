"""
Behavior Metrics for Backtesting
================================

Utility helpers for computing cross-persona behavioral diagnostics from
the existing backtest tracker and strategy-specific metrics payloads.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_behavior_metrics(tracker, strategy_metrics: Dict[str, Any] | None = None) -> Dict[str, float]:
    """
    Compute unified behavior metrics from tracker snapshots and strategy extras.

    Returned metrics are lightweight and provider-agnostic so they can be
    merged into the generic backtest metrics dict without changing the core
    tracker interfaces.
    """
    strategy_metrics = dict(strategy_metrics or {})
    summary = tracker.get_summary() if tracker is not None and hasattr(tracker, "get_summary") else {}
    snapshots = list(getattr(tracker, "snapshots", []) or [])

    avg_cash_ratio = 0.0
    avg_gross_exposure = 0.0
    if snapshots:
        cash_ratios = []
        exposures = []
        for snapshot in snapshots:
            total_value = _safe_float(getattr(snapshot, "total_value", None))
            cashflow = _safe_float(getattr(snapshot, "cashflow", None))
            if total_value > 0:
                cash_ratios.append(cashflow / total_value)
                exposures.append(max((total_value - cashflow) / total_value, 0.0))
        if cash_ratios:
            avg_cash_ratio = sum(cash_ratios) / len(cash_ratios)
        if exposures:
            avg_gross_exposure = sum(exposures) / len(exposures)

    behavior_metrics: Dict[str, float] = {
        "avg_cash_ratio": round(avg_cash_ratio, 4),
        "avg_gross_exposure": round(avg_gross_exposure, 4),
    }

    if "avg_turnover_ratio" in strategy_metrics:
        behavior_metrics["avg_turnover_ratio"] = round(_safe_float(strategy_metrics["avg_turnover_ratio"]), 4)
    elif "total_turnover_ratio" in strategy_metrics:
        behavior_metrics["avg_turnover_ratio"] = round(_safe_float(strategy_metrics["total_turnover_ratio"]), 4)

    if "peak_turnover_ratio" in strategy_metrics:
        behavior_metrics["peak_turnover_ratio"] = round(_safe_float(strategy_metrics["peak_turnover_ratio"]), 4)

    for key in (
        "value_filter_pass_rate",
        "value_consistency_score",
        "vol_scaling_activation_rate",
        "crash_breaker_trigger_count",
        "avg_momentum_exposure_multiplier",
        "tracking_error",
        "information_ratio",
        "fof_rebalance_total_turnover_ratio",
    ):
        if key in strategy_metrics:
            behavior_metrics[key] = strategy_metrics[key]

    return behavior_metrics
