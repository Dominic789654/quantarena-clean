"""Pure loaders for generated QuantArena report artifacts.

This module is intentionally read-only. It parses existing report files into
small structured objects so reporting and reproducibility tooling can share the
same artifact boundary without invoking backtest execution or report writers.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReportArtifactLoadError:
    """A structured artifact loading problem."""

    path: Path
    message: str


@dataclass
class RunReportArtifacts:
    """Loaded artifacts for one generated backtest report directory."""

    root: Path
    metrics_payload: dict[str, Any]
    metrics: dict[str, Any]
    equity_curve: list[dict[str, str]]
    trades: list[dict[str, str]]
    errors: list[ReportArtifactLoadError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def run_id(self) -> str | None:
        run_id = self.metrics_payload.get("run_id")
        return run_id if isinstance(run_id, str) else None

    @property
    def market(self) -> str | None:
        market = self.metrics_payload.get("market")
        return market if isinstance(market, str) else None

    @property
    def trading_days(self) -> int:
        return len(self.equity_curve)

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    def summary(self) -> dict[str, Any]:
        """Return a compact summary suitable for downstream report tooling."""
        return {
            "root": str(self.root),
            "ok": self.ok,
            "run_id": self.run_id,
            "market": self.market,
            "trading_days": self.trading_days,
            "trade_count": self.trade_count,
            "metric_keys": sorted(self.metrics),
            "errors": [
                {"path": str(error.path), "message": error.message}
                for error in self.errors
            ],
        }


def load_run_report_artifacts(root: str | Path) -> RunReportArtifacts:
    """Load metrics, equity curve, and trades from one report artifact directory."""
    report_root = Path(root)
    errors: list[ReportArtifactLoadError] = []

    metrics_payload = _load_metrics_payload(report_root / "metrics.json", errors)
    metrics = metrics_payload.get("metrics") if isinstance(metrics_payload.get("metrics"), dict) else {}
    if metrics_payload and not metrics:
        errors.append(
            ReportArtifactLoadError(
                path=report_root / "metrics.json",
                message="metrics.json must contain a metrics object",
            )
        )

    equity_curve = _load_csv_rows(report_root / "equity_curve.csv", errors)
    trades = _load_csv_rows(report_root / "trades.csv", errors)
    return RunReportArtifacts(
        root=report_root,
        metrics_payload=metrics_payload,
        metrics=metrics,
        equity_curve=equity_curve,
        trades=trades,
        errors=errors,
    )


def _load_metrics_payload(
    path: Path,
    errors: list[ReportArtifactLoadError],
) -> dict[str, Any]:
    if not path.is_file():
        errors.append(ReportArtifactLoadError(path=path, message="missing required artifact"))
        return {}

    try:
        raw_payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(ReportArtifactLoadError(path=path, message=f"unable to read JSON: {exc}"))
        return {}

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        errors.append(ReportArtifactLoadError(path=path, message=f"invalid JSON: {exc}"))
        return {}

    if not isinstance(payload, dict):
        errors.append(ReportArtifactLoadError(path=path, message="metrics.json must be an object"))
        return {}
    return payload


def _load_csv_rows(
    path: Path,
    errors: list[ReportArtifactLoadError],
) -> list[dict[str, str]]:
    if not path.is_file():
        errors.append(ReportArtifactLoadError(path=path, message="missing required artifact"))
        return []

    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                errors.append(ReportArtifactLoadError(path=path, message="CSV header is missing"))
                return []
            return list(reader)
    except (csv.Error, OSError, UnicodeDecodeError) as exc:
        errors.append(ReportArtifactLoadError(path=path, message=f"unable to read CSV: {exc}"))
        return []
