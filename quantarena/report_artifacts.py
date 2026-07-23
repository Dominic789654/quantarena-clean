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
    broker_audit: list[dict[str, Any]] = field(default_factory=list)
    run_manifest: dict[str, Any] = field(default_factory=dict)
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

    @property
    def broker_audit_count(self) -> int:
        return len(self.broker_audit)

    def summary(self) -> dict[str, Any]:
        """Return a compact summary suitable for downstream report tooling."""
        return {
            "root": str(self.root),
            "ok": self.ok,
            "run_id": self.run_id,
            "market": self.market,
            "trading_days": self.trading_days,
            "trade_count": self.trade_count,
            "broker_audit_count": self.broker_audit_count,
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
    broker_audit = _load_optional_jsonl_rows(report_root / "broker_audit.jsonl", errors)
    run_manifest = _load_optional_json_object(report_root / "run_manifest.json", errors)
    return RunReportArtifacts(
        root=report_root,
        metrics_payload=metrics_payload,
        metrics=metrics,
        equity_curve=equity_curve,
        trades=trades,
        broker_audit=broker_audit,
        run_manifest=run_manifest,
        errors=errors,
    )


def _load_optional_json_object(
    path: Path,
    errors: list[ReportArtifactLoadError],
) -> dict[str, Any]:
    """Load an optional JSON-object artifact; absent files are not errors
    (runs generated before the artifact existed remain valid)."""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(ReportArtifactLoadError(path=path, message=f"unreadable artifact: {exc}"))
        return {}
    if not isinstance(payload, dict):
        errors.append(ReportArtifactLoadError(path=path, message="artifact must be a JSON object"))
        return {}
    return payload


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


def _load_optional_jsonl_rows(
    path: Path,
    errors: list[ReportArtifactLoadError],
) -> list[dict[str, Any]]:
    if not path.is_file():
        return []

    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(
                        ReportArtifactLoadError(
                            path=path,
                            message=f"invalid JSONL on line {line_number}: {exc}",
                        )
                    )
                    continue
                if not isinstance(payload, dict):
                    errors.append(
                        ReportArtifactLoadError(
                            path=path,
                            message=f"JSONL line {line_number} must be an object",
                        )
                    )
                    continue
                rows.append(payload)
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(ReportArtifactLoadError(path=path, message=f"unable to read JSONL: {exc}"))
        return []
    return rows
