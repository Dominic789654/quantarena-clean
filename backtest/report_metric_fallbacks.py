"""Fallback metric loaders for backtest report generation."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from quantarena.report_artifacts import load_run_report_artifacts


TURNOVER_METRIC_KEYS = (
    "avg_turnover_ratio",
    "peak_turnover_ratio",
    "annualized_turnover_ratio",
    "total_turnover_ratio",
)

EXPOSURE_METRIC_KEYS = (
    "avg_cash_ratio",
    "avg_gross_exposure",
)

CSV_NA_TOKENS = {"", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan",
                 "1.#IND", "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None",
                 "n/a", "nan", "null"}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows_to_dataframe(rows: list[dict[str, str]]) -> Optional[pd.DataFrame]:
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df = df.map(lambda value: pd.NA if isinstance(value, str) and value in CSV_NA_TOKENS else value)
    for column in df.columns:
        series = df[column]
        non_empty = series.notna()
        if not non_empty.any():
            continue
        converted = pd.to_numeric(series, errors="coerce")
        if converted[non_empty].notna().all():
            df[column] = converted
    return df


def compute_turnover_metrics_from_report_dir(
    report_dir: Path,
    trading_days_per_year: int = 252,
    initial_cash: float | None = None,
) -> Dict[str, float]:
    """Reconstruct turnover metrics from persisted trades and equity snapshots."""
    artifacts = load_run_report_artifacts(report_dir)
    trades_df = _rows_to_dataframe(artifacts.trades)
    equity_df = _rows_to_dataframe(artifacts.equity_curve)
    if trades_df is None or equity_df is None or trades_df.empty or equity_df.empty:
        return {}

    if "date" not in trades_df.columns or "date" not in equity_df.columns:
        return {}
    if "value" not in trades_df.columns or "total_value" not in equity_df.columns:
        return {}

    trades_df = trades_df.copy()
    equity_df = equity_df.copy()
    trades_df["date"] = pd.to_datetime(trades_df["date"], errors="coerce")
    equity_df["date"] = pd.to_datetime(equity_df["date"], errors="coerce")
    trades_df = trades_df.dropna(subset=["date"])
    equity_df = equity_df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if trades_df.empty or equity_df.empty:
        return {}

    traded_value_by_date = trades_df.groupby("date", as_index=True)["value"].sum()
    turnover_series: list[float] = []

    first_snapshot = equity_df.iloc[0]
    first_date = first_snapshot["date"]
    first_denominator = float(initial_cash or 0.0)
    if first_denominator <= 0:
        first_denominator = float(first_snapshot.get("total_value", 0.0) or 0.0)
    if math.isfinite(first_denominator) and first_denominator > 0:
        first_traded_value = float(traded_value_by_date.get(first_date, 0.0) or 0.0)
        if not math.isfinite(first_traded_value):
            first_traded_value = 0.0
        turnover_series.append(first_traded_value / (2.0 * first_denominator))

    for idx in range(1, len(equity_df)):
        snapshot_date = equity_df.iloc[idx]["date"]
        previous_total_value = float(equity_df.iloc[idx - 1].get("total_value", 0.0) or 0.0)
        if not math.isfinite(previous_total_value) or previous_total_value <= 0:
            turnover_series.append(0.0)
            continue
        traded_value = float(traded_value_by_date.get(snapshot_date, 0.0) or 0.0)
        if not math.isfinite(traded_value):
            traded_value = 0.0
        turnover_series.append(traded_value / (2.0 * previous_total_value))

    if not turnover_series:
        return {}

    avg_turnover = sum(turnover_series) / len(turnover_series)
    peak_turnover = max(turnover_series)
    total_turnover = sum(turnover_series)
    return {
        "avg_turnover_ratio": round(avg_turnover, 4),
        "peak_turnover_ratio": round(peak_turnover, 4),
        "annualized_turnover_ratio": round(avg_turnover * trading_days_per_year, 4),
        "total_turnover_ratio": round(total_turnover, 4),
    }


def compute_exposure_metrics_from_report_dir(report_dir: Path) -> Dict[str, float]:
    """Reconstruct cash/exposure averages from persisted equity snapshots."""
    artifacts = load_run_report_artifacts(report_dir)
    equity_df = _rows_to_dataframe(artifacts.equity_curve)
    if equity_df is None or equity_df.empty:
        return {}
    if "cashflow" not in equity_df.columns or "total_value" not in equity_df.columns:
        return {}

    valid = equity_df[equity_df["total_value"].fillna(0) > 0].copy()
    if valid.empty:
        return {}

    cash_ratios = valid["cashflow"].astype(float) / valid["total_value"].astype(float)
    gross_exposure = (valid["total_value"].astype(float) - valid["cashflow"].astype(float)) / valid["total_value"].astype(float)
    return {
        "avg_cash_ratio": round(float(cash_ratios.mean()), 4),
        "avg_gross_exposure": round(float(gross_exposure.clip(lower=0.0).mean()), 4),
    }


def enrich_behavior_metrics(
    metrics: Dict[str, Any] | None,
    report_dir: str | Path | None,
    trading_days_per_year: int = 252,
) -> Dict[str, Any]:
    """Fill missing behavior metrics from persisted report artifacts when possible."""
    enriched: Dict[str, Any] = dict(metrics or {})
    if report_dir is None:
        return enriched

    target_dir = Path(report_dir)
    if not target_dir.exists():
        return enriched

    initial_cash = None
    try:
        if "initial_cash" in enriched and enriched["initial_cash"] is not None:
            initial_cash = float(enriched["initial_cash"])
    except (TypeError, ValueError):
        initial_cash = None

    reconstructed_turnover = compute_turnover_metrics_from_report_dir(
        target_dir,
        trading_days_per_year,
        initial_cash=initial_cash,
    )
    if reconstructed_turnover:
        missing_turnover_key = any(key not in enriched for key in TURNOVER_METRIC_KEYS)
        stale_zero_turnover = any(
            reconstructed_turnover.get(key, 0.0) > 0.0 and (_safe_float(enriched.get(key)) or 0.0) <= 0.0
            for key in TURNOVER_METRIC_KEYS
        )
        if missing_turnover_key or stale_zero_turnover:
            enriched.update(reconstructed_turnover)

    reconstructed_exposure = compute_exposure_metrics_from_report_dir(target_dir)
    if reconstructed_exposure:
        missing_exposure_key = any(key not in enriched for key in EXPOSURE_METRIC_KEYS)
        stale_zero_exposure = any(
            reconstructed_exposure.get(key, 0.0) > 0.0 and (_safe_float(enriched.get(key)) or 0.0) <= 0.0
            for key in EXPOSURE_METRIC_KEYS
        )
        if missing_exposure_key or stale_zero_exposure:
            enriched.update(reconstructed_exposure)

    return enriched
