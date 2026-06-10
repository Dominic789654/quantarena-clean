"""Post-run consistency checks for generated backtest artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quantarena.report_artifacts import RunReportArtifacts, load_run_report_artifacts


SPECIALIZED_METRIC_KEYS: dict[str, tuple[str, ...]] = {
    "fundamental_value": ("value_filter_pass_rate", "value_consistency_score"),
    "value": ("value_filter_pass_rate", "value_consistency_score"),
    "behavioral_momentum": (
        "vol_scaling_activation_rate",
        "crash_breaker_trigger_count",
        "avg_momentum_exposure_multiplier",
    ),
    "momentum": (
        "vol_scaling_activation_rate",
        "crash_breaker_trigger_count",
        "avg_momentum_exposure_multiplier",
    ),
}


@dataclass(frozen=True)
class BacktestArtifactFinding:
    """One artifact review finding."""

    severity: str
    personality: str
    run_id: str
    message: str


@dataclass
class BacktestArtifactReview:
    """Result of reviewing a multi-personality report directory."""

    root: Path
    findings: list[BacktestArtifactFinding] = field(default_factory=list)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(finding.severity == "error" for finding in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "ok": self.ok,
            "findings": [
                {
                    "severity": finding.severity,
                    "personality": finding.personality,
                    "run_id": finding.run_id,
                    "message": finding.message,
                }
                for finding in self.findings
            ],
            "runs": self.runs,
            "artifacts": self.artifacts,
        }


def review_multi_personality_artifacts(
    report_dir: str | Path,
    *,
    backtest_root: str | Path | None = None,
) -> BacktestArtifactReview:
    """Review generated multi-personality artifacts for execution consistency."""
    root = Path(report_dir)
    review = BacktestArtifactReview(root=root)
    comparison_path = root / "comparison_data.json"
    if not comparison_path.is_file():
        review.findings.append(
            BacktestArtifactFinding(
                severity="error",
                personality="",
                run_id="",
                message=f"missing comparison_data.json at {comparison_path}",
            )
        )
        return review

    try:
        comparison_payload = json.loads(comparison_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        review.findings.append(
            BacktestArtifactFinding(
                severity="error",
                personality="",
                run_id="",
                message=f"unable to read comparison_data.json: {exc}",
            )
        )
        return review

    artifact_schema_version = int(comparison_payload.get("artifact_schema_version", 1) or 1)
    require_v2_artifacts = artifact_schema_version >= 2
    daily_decisions = _load_jsonl_artifact(
        review,
        root / "daily_decisions.jsonl",
        required=require_v2_artifacts,
    )
    news_diagnostics = _load_jsonl_artifact(
        review,
        root / "news_diagnostics.jsonl",
        required=require_v2_artifacts,
    )
    review.artifacts = {
        "artifact_schema_version": artifact_schema_version,
        "daily_decisions_count": len(daily_decisions),
        "news_diagnostics_count": len(news_diagnostics),
    }
    if require_v2_artifacts and not daily_decisions:
        review.findings.append(
            BacktestArtifactFinding(
                severity="error",
                personality="",
                run_id=str(comparison_payload.get("run_id") or ""),
                message="daily_decisions.jsonl is missing or empty",
            )
        )

    base_backtest_root = Path(backtest_root) if backtest_root is not None else root.parents[1] / "backtest"
    for result in _iter_personality_results(comparison_payload):
        personality = str(result.get("personality") or "")
        run_id = str(result.get("run_id") or "")
        if not personality or not run_id:
            review.findings.append(
                BacktestArtifactFinding(
                    severity="error",
                    personality=personality,
                    run_id=run_id,
                    message="personality result is missing personality or run_id",
                )
            )
            continue

        artifacts = load_run_report_artifacts(base_backtest_root / run_id)
        _record_run_summary(review, personality, run_id, artifacts)
        _check_load_errors(review, personality, run_id, artifacts)
        _check_trade_audit_consistency(review, personality, run_id, artifacts)
        _check_specialized_metrics(review, personality, run_id, artifacts)

    return review


def _load_jsonl_artifact(
    review: BacktestArtifactReview,
    path: Path,
    *,
    required: bool,
) -> list[dict[str, Any]]:
    if not path.is_file():
        if required:
            review.findings.append(
                BacktestArtifactFinding(
                    severity="error",
                    personality="",
                    run_id="",
                    message=f"missing required artifact: {path.name}",
                )
            )
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
                    review.findings.append(
                        BacktestArtifactFinding(
                            severity="error",
                            personality="",
                            run_id="",
                            message=f"{path.name} line {line_number} invalid JSON: {exc}",
                        )
                    )
                    continue
                if not isinstance(payload, dict):
                    review.findings.append(
                        BacktestArtifactFinding(
                            severity="error",
                            personality="",
                            run_id="",
                            message=f"{path.name} line {line_number} must be an object",
                        )
                    )
                    continue
                rows.append(payload)
    except (OSError, UnicodeDecodeError) as exc:
        review.findings.append(
            BacktestArtifactFinding(
                severity="error",
                personality="",
                run_id="",
                message=f"unable to read {path.name}: {exc}",
            )
        )
    return rows


def _iter_personality_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_results = payload.get("personality_results")
    if isinstance(raw_results, list):
        return [item for item in raw_results if isinstance(item, dict)]
    if isinstance(raw_results, dict):
        return [item for item in raw_results.values() if isinstance(item, dict)]
    return []


def _record_run_summary(
    review: BacktestArtifactReview,
    personality: str,
    run_id: str,
    artifacts: RunReportArtifacts,
) -> None:
    review.runs[personality] = {
        "run_id": run_id,
        "report_dir": str(artifacts.root),
        "trade_count": artifacts.trade_count,
        "broker_audit_count": artifacts.broker_audit_count,
        "metric_keys": sorted(artifacts.metrics),
    }


def _check_load_errors(
    review: BacktestArtifactReview,
    personality: str,
    run_id: str,
    artifacts: RunReportArtifacts,
) -> None:
    for error in artifacts.errors:
        review.findings.append(
            BacktestArtifactFinding(
                severity="error",
                personality=personality,
                run_id=run_id,
                message=f"{error.path}: {error.message}",
            )
        )


def _check_trade_audit_consistency(
    review: BacktestArtifactReview,
    personality: str,
    run_id: str,
    artifacts: RunReportArtifacts,
) -> None:
    if artifacts.trade_count > 0 and artifacts.broker_audit_count == 0:
        review.findings.append(
            BacktestArtifactFinding(
                severity="error",
                personality=personality,
                run_id=run_id,
                message="trades.csv contains trades but broker_audit.jsonl has no events",
            )
        )
    if artifacts.broker_audit_count > 0 and artifacts.broker_audit_count < artifacts.trade_count:
        review.findings.append(
            BacktestArtifactFinding(
                severity="warning",
                personality=personality,
                run_id=run_id,
                message=(
                    "broker_audit.jsonl has fewer events than trades.csv; "
                    "verify whether rejected attempts or non-paper paths are expected"
                ),
            )
        )


def _check_specialized_metrics(
    review: BacktestArtifactReview,
    personality: str,
    run_id: str,
    artifacts: RunReportArtifacts,
) -> None:
    required_keys = SPECIALIZED_METRIC_KEYS.get(personality)
    if not required_keys:
        return
    missing = [key for key in required_keys if key not in artifacts.metrics]
    if missing:
        review.findings.append(
            BacktestArtifactFinding(
                severity="error",
                personality=personality,
                run_id=run_id,
                message=f"specialized metrics missing: {', '.join(missing)}",
            )
        )
