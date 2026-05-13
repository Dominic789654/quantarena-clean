#!/usr/bin/env python
"""
Regenerate comparison report from existing individual personality backtest results.

This script reads existing report artifacts from individual backtest runs and
regenerates the comparison report without re-running the entire backtest.
"""

import sys
import json
from pathlib import Path
from typing import Dict, Any, List

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()

from backtest.report_metric_fallbacks import enrich_behavior_metrics
from quantarena.report_artifacts import RunReportArtifacts, load_run_report_artifacts


BACKTEST_REPORTS_DIR = Path("reports/backtest")
COMPARISON_REPORTS_DIR = Path("reports/multi_personality")


class RegenerationError(RuntimeError):
    """Raised when a comparison report cannot be reconstructed faithfully."""


def _metrics_load_error_message(artifacts: RunReportArtifacts) -> str | None:
    """Return the required metrics artifact error, if metrics cannot be trusted."""
    metrics_errors = [
        f"{error.path.name}: {error.message}"
        for error in artifacts.errors
        if error.path.name == "metrics.json"
    ]
    if metrics_errors:
        return "; ".join(metrics_errors)
    if not artifacts.metrics:
        return "metrics.json: missing or empty metrics object"
    return None


def _safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_avg_position_days(
    target_dir: Path,
    metrics: Dict[str, Any],
    artifacts: RunReportArtifacts | None = None,
) -> float:
    """Load avg_position_days from metrics, or reconstruct it from trades.csv when absent."""
    if "avg_position_days" in metrics:
        return _safe_float(metrics.get("avg_position_days", 0))

    loaded_artifacts = artifacts or load_run_report_artifacts(target_dir)
    if not loaded_artifacts.trades:
        return 0.0

    from backtest.portfolio_tracker import PortfolioTracker

    tracker = PortfolioTracker()
    for trade in loaded_artifacts.trades:
        tracker.record_trade(
            date=str(trade.get("date", "")),
            ticker=str(trade.get("ticker", "")),
            action=str(trade.get("action", "HOLD")),
            shares=_safe_int(trade.get("shares", 0)),
            price=_safe_float(trade.get("price", 0.0)),
            justification=str(trade.get("justification", "") or ""),
        )

    return tracker.calculate_avg_position_days()


def _comparison_data_path(run_id: str, comparison_reports_dir: Path = COMPARISON_REPORTS_DIR) -> Path:
    return comparison_reports_dir / run_id / "comparison_data.json"


def _load_comparison_data(run_id: str, comparison_reports_dir: Path = COMPARISON_REPORTS_DIR) -> Dict[str, Any]:
    """Load persisted comparison metadata when available."""
    comparison_path = _comparison_data_path(run_id, comparison_reports_dir)
    if not comparison_path.exists():
        return {}
    try:
        with open(comparison_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load comparison data from {comparison_path}: {e}")
        return {}


def load_comparison_personality_run_ids(
    run_id: str,
    comparison_reports_dir: Path = COMPARISON_REPORTS_DIR,
) -> Dict[str, str]:
    """Load exact per-personality backtest run IDs from persisted comparison data."""
    data = _load_comparison_data(run_id, comparison_reports_dir)
    personality_results = data.get("personality_results", {}) or {}
    run_ids: Dict[str, str] = {}
    for personality, payload in personality_results.items():
        if not isinstance(payload, dict):
            continue
        personality_run_id = str(payload.get("run_id", "") or "").strip()
        if personality_run_id:
            run_ids[str(personality)] = personality_run_id
    return run_ids


def load_comparison_personality_rows(
    run_id: str,
    comparison_reports_dir: Path = COMPARISON_REPORTS_DIR,
) -> Dict[str, Dict[str, Any]]:
    """Load preserved per-personality comparison rows from existing report data."""
    data = _load_comparison_data(run_id, comparison_reports_dir)
    personality_results = data.get("personality_results", {}) or {}
    rows: Dict[str, Dict[str, Any]] = {}
    for personality, payload in personality_results.items():
        if isinstance(payload, dict):
            rows[str(personality)] = dict(payload)
    return rows


def _discover_personality_dirs(
    run_id: str,
    personalities: List[str],
    backtest_reports_dir: Path = BACKTEST_REPORTS_DIR,
    comparison_reports_dir: Path = COMPARISON_REPORTS_DIR,
) -> Dict[str, Path]:
    """Find per-personality report dirs matching a historical multi-personality run."""
    resolved: Dict[str, Path] = {}
    explicit_run_ids = load_comparison_personality_run_ids(run_id, comparison_reports_dir)
    personalities_with_missing_explicit_dirs: set[str] = set()

    for personality in personalities:
        explicit_run_id = explicit_run_ids.get(personality)
        if not explicit_run_id:
            continue
        target_dir = backtest_reports_dir / explicit_run_id
        if target_dir.exists():
            resolved[personality] = target_dir
        else:
            personalities_with_missing_explicit_dirs.add(personality)
            print(
                f"Warning: comparison_data.json references missing run dir for {personality}: {explicit_run_id}"
            )

    missing = [personality for personality in personalities if personality not in resolved]
    if not missing:
        return resolved

    # Older report bundles may embed the parent comparison run ID directly in each
    # per-personality directory name. That path is deterministic, so we allow it
    # only for personalities that do not already have an explicit missing run id.
    for personality in missing:
        if personality in personalities_with_missing_explicit_dirs:
            continue
        pattern = f"mp_{personality}_*"
        matching_dirs = list(backtest_reports_dir.glob(pattern))
        target_dir = next((d for d in matching_dirs if run_id in d.name), None)
        if target_dir is not None:
            resolved[personality] = target_dir

    return resolved


def _is_failed_personality_row(payload: Dict[str, Any] | None) -> bool:
    """Whether a preserved comparison row represents a failed personality run."""
    if not payload:
        return False
    try:
        return int(payload.get("error_count", 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def _build_preserved_personality_result(personality: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a preserved comparison row for regeneration output."""
    metrics = dict(payload.get("metrics", {}) or {})
    return {
        "personality": personality,
        "run_id": payload.get("run_id"),
        "total_return": float(payload.get("total_return", 0) or 0),
        "max_drawdown": float(payload.get("max_drawdown", 0) or 0),
        "sharpe_ratio": float(payload.get("sharpe_ratio", 0) or 0),
        "trade_count": int(payload.get("trade_count", 0) or 0),
        "win_rate": float(payload.get("win_rate", 0) or 0),
        "avg_position_days": float(payload.get("avg_position_days", 0) or 0),
        "metrics": metrics,
        "token_usage": dict(payload.get("token_usage", {}) or {}),
        "error_count": int(payload.get("error_count", 0) or 0),
        "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
    }


def load_existing_results(
    run_id: str,
    personalities: List[str] | None = None,
    backtest_reports_dir: Path = BACKTEST_REPORTS_DIR,
    comparison_reports_dir: Path = COMPARISON_REPORTS_DIR,
) -> Dict[str, Any]:
    """
    Load existing results from the individual backtest directories.

    Args:
        run_id: The original multi-personality run ID (e.g., "20260224_072137")

    Returns:
        Dict with all personality results
    """
    personalities = list(personalities or ["aggressive", "balanced", "conservative", "passive"])
    results = {}
    preserved_rows = load_comparison_personality_rows(run_id, comparison_reports_dir)
    discovered_dirs = _discover_personality_dirs(
        run_id,
        personalities,
        backtest_reports_dir=backtest_reports_dir,
        comparison_reports_dir=comparison_reports_dir,
    )

    for personality in personalities:
        target_dir = discovered_dirs.get(personality)
        preserved_row = preserved_rows.get(personality, {})
        if target_dir is None:
            if _is_failed_personality_row(preserved_row):
                results[personality] = _build_preserved_personality_result(personality, preserved_row)
                print(f"Preserved failed personality row for {personality}")
                continue
            raise RegenerationError(
                "Cannot regenerate comparison report faithfully; missing exact source run for "
                f"{personality}."
            )

        try:
            artifacts = load_run_report_artifacts(target_dir)
            metrics_error = _metrics_load_error_message(artifacts)
            if metrics_error is not None:
                raise RegenerationError(metrics_error)

            m = enrich_behavior_metrics(artifacts.metrics, target_dir)
            total_return = m.get("total_return", 0)
            max_drawdown = m.get("max_drawdown", 0)
            sharpe_ratio = m.get("sharpe_ratio", 0)
            trade_count = m.get("total_trades", 0)
            win_rate = m.get("win_rate", 0) / 100  # Normalize to 0-1
            avg_position_days = _load_avg_position_days(target_dir, m, artifacts=artifacts)

            results[personality] = {
                "personality": personality,
                "run_id": target_dir.name,
                "total_return": total_return,
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe_ratio,
                "trade_count": trade_count,
                "win_rate": win_rate,
                "avg_position_days": avg_position_days,
                "metrics": m,
                "token_usage": {},  # Would need to get from another source
                "error_count": 0,
                "duration_seconds": 0,
            }
            print(f"Loaded {personality}: Return={total_return:+.2f}%, Trades={trade_count}")
        except Exception as e:
            if _is_failed_personality_row(preserved_row):
                results[personality] = _build_preserved_personality_result(personality, preserved_row)
                print(f"Preserved failed personality row for {personality}")
                continue
            raise RegenerationError(f"Error loading {personality} from {target_dir}: {e}") from e

    return results


def load_comparison_config(
    run_id: str,
    comparison_reports_dir: Path = COMPARISON_REPORTS_DIR,
) -> Dict[str, Any]:
    """Load the original comparison_data.json to get the config."""
    data = _load_comparison_data(run_id, comparison_reports_dir)
    if data:
        return data.get("config", {})

    # Default config
    return {
        "tickers": ["600519", "000858", "601318", "300750", "600036"],
        "start_date": "2025-10-01",
        "end_date": "2025-10-31",
        "market": "cn",
        "trading_days": 17,
        "initial_cash": 100000.0,
        "analysts": ["fundamental", "technical", "company_news"]
    }


def load_comparison_personalities(
    run_id: str,
    comparison_reports_dir: Path = COMPARISON_REPORTS_DIR,
) -> List[str]:
    """Load personality names from existing comparison data when available."""
    data = _load_comparison_data(run_id, comparison_reports_dir)
    if data:
        personality_results = data.get("personality_results", {}) or {}
        if personality_results:
            return list(personality_results.keys())
        config = data.get("config", {}) or {}
        personalities = config.get("personalities", []) or []
        if personalities:
            return list(personalities)
    return ["aggressive", "balanced", "conservative", "passive"]


def generate_markdown_report(
    comparison: Dict[str, Any],
    config: Dict[str, Any],
    initial_cash: float,
) -> str:
    """Generate markdown comparison report from existing results."""

    def _format_optional(value: Any, fmt: str) -> str:
        try:
            if value is None:
                return "-"
            return format(float(value), fmt)
        except (TypeError, ValueError):
            return "-"

    def _generate_behavior_metrics_table() -> str:
        lines = ["### 行为诊断指标\n\n"]
        lines.append("| 人格 | 平均换手 | 平均现金占比 | 平均总暴露 | 价值一致性 | 动量缩放激活率 | 熔断触发次数 |\n")
        lines.append("|------|----------|--------------|------------|------------|------------------|--------------|\n")

        for personality, result in comparison["personality_results"].items():
            metrics = result.get("metrics", {}) or {}
            value_score = metrics.get("value_consistency_score")
            vol_activation = metrics.get("vol_scaling_activation_rate")
            crash_count = metrics.get("crash_breaker_trigger_count")

            lines.append(
                f"| {personality} | "
                f"{float(metrics.get('avg_turnover_ratio', 0.0) or 0.0):.2%} | "
                f"{float(metrics.get('avg_cash_ratio', 0.0) or 0.0):.2%} | "
                f"{float(metrics.get('avg_gross_exposure', 0.0) or 0.0):.2%} | "
                f"{_format_optional(value_score, '.4f')} | "
                f"{_format_optional(vol_activation, '.4f')} | "
                f"{_format_optional(crash_count, '.0f')} |\n"
            )

        return "".join(lines)

    def _generate_performance_table() -> str:
        lines = ["### 收益与风险指标\n\n"]
        lines.append("| 人格 | 总收益率 | 最大回撤 | 夏普比率 | 最终资产 | 排名 |\n")
        lines.append("|------|----------|----------|----------|----------|------|\n")

        sorted_results = sorted(
            comparison["personality_results"].items(),
            key=lambda item: item[1].get("total_return", 0),
            reverse=True,
        )

        for index, (personality, result) in enumerate(sorted_results, 1):
            final_value = initial_cash * (1 + result.get("total_return", 0) / 100)
            lines.append(
                f"| **{personality}** | "
                f"{result.get('total_return', 0):+.2f}% | "
                f"{result.get('max_drawdown', 0):.2f}% | "
                f"{result.get('sharpe_ratio', 0):.2f} | "
                f"¥{final_value:,.0f} | "
                f"{index} |\n"
            )

        return "".join(lines)

    def _generate_detailed_analysis() -> str:
        lines = []
        for personality, result in comparison["personality_results"].items():
            metrics = result.get("metrics", {}) or {}
            lines.append(f"\n### {personality.upper()} 详细分析\n\n")
            if result.get("error_count", 0) > 0:
                lines.append(f"⚠️ **警告**: 运行中出现 {result.get('error_count', 0)} 个错误\n\n")
            lines.append(f"- **运行耗时**: {result.get('duration_seconds', 0):.2f} 秒\n")
            lines.append(f"- **交易次数**: {result.get('trade_count', 0)} 次\n")
            win_rate = result.get("win_rate", 0)
            win_rate_pct = win_rate * 100 if win_rate <= 1 else win_rate
            lines.append(f"- **胜率**: {win_rate_pct:.1f}%\n")
            lines.append(f"- **平均持仓天数**: {result.get('avg_position_days', 0):.1f} 天\n")
            lines.append(f"- **平均换手率**: {float(metrics.get('avg_turnover_ratio', 0.0) or 0.0):.2%}\n")
            lines.append(f"- **平均现金占比**: {float(metrics.get('avg_cash_ratio', 0.0) or 0.0):.2%}\n")
            lines.append(f"- **平均总暴露**: {float(metrics.get('avg_gross_exposure', 0.0) or 0.0):.2%}\n")
        return "".join(lines)

    def _generate_trading_behavior_table() -> str:
        lines = ["### 交易行为统计\n\n"]
        lines.append("| 人格 | 交易次数 | 胜率 | 平均持仓天数 | 运行耗时 | 错误数 |\n")
        lines.append("|------|----------|------|--------------|----------|--------|\n")

        for personality, result in comparison["personality_results"].items():
            win_rate = result.get("win_rate", 0)
            win_rate_pct = win_rate * 100 if win_rate <= 1 else win_rate
            lines.append(
                f"| **{personality}** | "
                f"{result.get('trade_count', 0)} | "
                f"{win_rate_pct:.1f}% | "
                f"{result.get('avg_position_days', 0):.1f} | "
                f"{result.get('duration_seconds', 0):.2f}s | "
                f"{result.get('error_count', 0)} |\n"
            )

        return "".join(lines)

    def _generate_conclusions() -> str:
        sorted_results = sorted(
            comparison["personality_results"].items(),
            key=lambda item: item[1].get("total_return", 0),
            reverse=True,
        )
        best_personality, best_result = sorted_results[0]
        lines = [
            f"### 最佳表现: **{best_personality.upper()}**\n\n",
            f"- 总收益率: {best_result.get('total_return', 0):+.2f}%\n",
            f"- 最大回撤: {best_result.get('max_drawdown', 0):.2f}%\n",
            f"- 夏普比率: {best_result.get('sharpe_ratio', 0):.2f}\n",
        ]
        return "".join(lines)

    c = comparison
    shared_stats = c.get("shared_data_stats", {}) or {}
    prefetch_submitted = shared_stats.get("shared_phase1_prefetch_submitted", 0)
    prefetch_hits = shared_stats.get("shared_phase1_prefetch_hits", 0)
    prefetch_hit_rate = shared_stats.get("shared_phase1_prefetch_hit_rate")
    if prefetch_hit_rate is None:
        prefetch_hit_rate = (prefetch_hits / prefetch_submitted) if prefetch_submitted else 0.0
    prefetch_compute_seconds = shared_stats.get("shared_phase1_prefetch_compute_seconds", 0.0)
    prefetch_wait_seconds = shared_stats.get("shared_phase1_prefetch_wait_seconds", 0.0)
    pipeline_hidden_seconds = shared_stats.get("shared_phase1_pipeline_hidden_seconds")
    if pipeline_hidden_seconds is None:
        pipeline_hidden_seconds = max(0.0, prefetch_compute_seconds - prefetch_wait_seconds)
    pipeline_utilization = shared_stats.get("shared_phase1_pipeline_utilization")
    if pipeline_utilization is None:
        pipeline_utilization = (pipeline_hidden_seconds / prefetch_compute_seconds) if prefetch_compute_seconds else 0.0

    lines = [
        "# 多人格投资风格对比回测报告\n",
        f"**运行ID**: `{c['run_id']}`\n",
        f"**回测周期**: {config['start_date']} ~ {config['end_date']} ({config['trading_days']} 个交易日)\n",
        f"**股票池**: {', '.join(config['tickers'])}\n",
        f"**市场**: {config['market'].upper()}\n",
        f"**初始资金**: ¥{initial_cash:,.0f}\n",
        f"**总耗时**: {c.get('total_duration', 0):.2f} 秒\n",
        "\n---\n\n",
        "## 共享数据缓存统计\n",
        f"- K-line 数据获取时间: {shared_stats.get('kline_fetch_time', 0):.2f}s\n",
        f"- DeepEar 数据获取时间: {shared_stats.get('deepear_fetch_time', 0):.2f}s\n",
        f"- 数据缓存总时间: {shared_stats.get('total_time', 0):.2f}s\n",
        f"- shared phase1 artifact cache 命中: {shared_stats.get('shared_phase1_artifact_cache_hits', 0)}\n",
        f"- shared phase1 artifact cache 未命中: {shared_stats.get('shared_phase1_artifact_cache_misses', 0)}\n",
        f"- shared phase1 同步装载耗时: {shared_stats.get('shared_phase1_sync_load_seconds', 0.0):.2f}s\n",
        f"- shared phase1 预取提交次数: {prefetch_submitted}\n",
        f"- shared phase1 预取命中次数: {prefetch_hits} ({prefetch_hit_rate * 100:.1f}%)\n",
        f"- shared phase1 预取失败次数: {shared_stats.get('shared_phase1_prefetch_failures', 0)}\n",
        f"- shared phase1 预取后台耗时: {prefetch_compute_seconds:.2f}s\n",
        f"- shared phase1 进入新交易日等待耗时: {prefetch_wait_seconds:.2f}s\n",
        f"- shared phase1 pipeline 隐藏耗时: {pipeline_hidden_seconds:.2f}s\n",
        f"- shared phase1 pipeline 利用率: {pipeline_utilization * 100:.1f}%\n",
        f"- shared phase1 预取失败后同步回退耗时: {shared_stats.get('shared_phase1_prefetch_fallback_sync_seconds', 0.0):.2f}s\n",
        "\n---\n\n",
        "## 各人格表现对比\n",
        _generate_performance_table(),
        "\n---\n\n",
        "## 详细指标分析\n",
        _generate_detailed_analysis(),
        "\n---\n\n",
        "## 行为指标对比\n",
        _generate_behavior_metrics_table(),
        "\n---\n\n",
        "## 交易行为对比\n",
        _generate_trading_behavior_table(),
        "\n---\n\n",
        "## 结论与建议\n",
        _generate_conclusions(),
    ]

    return "".join(lines)


def regenerate_report(
    run_id: str,
    backtest_reports_dir: Path = BACKTEST_REPORTS_DIR,
    comparison_reports_dir: Path = COMPARISON_REPORTS_DIR,
):
    """Regenerate the comparison report for a given run ID."""
    print(f"Regenerating comparison report for run: {run_id}")

    original_data = _load_comparison_data(run_id, comparison_reports_dir)
    if not original_data:
        raise RegenerationError(
            f"Missing original comparison_data.json for {run_id}; cannot regenerate report faithfully."
        )

    # 1. Load existing personality results
    print("\nLoading personality results...")
    personalities = load_comparison_personalities(run_id, comparison_reports_dir)
    personality_results = load_existing_results(
        run_id,
        personalities,
        backtest_reports_dir=backtest_reports_dir,
        comparison_reports_dir=comparison_reports_dir,
    )

    if not personality_results:
        raise RegenerationError("No personality results were loaded.")

    # 2. Load config
    config = load_comparison_config(run_id, comparison_reports_dir)
    initial_cash = config.get("initial_cash", 100000.0)

    # 3. Build comparison structure
    comparison = {
        "run_id": run_id,
        "start_date": config["start_date"],
        "end_date": config["end_date"],
        "tickers": config["tickers"],
        "market": config["market"],
        "trading_days": config["trading_days"],
        "personality_results": personality_results,
        "shared_data_stats": original_data.get("shared_data_stats", {}) or {},
        "total_duration": original_data.get("total_duration", 0.0),
    }

    # 4. Generate reports
    report_dir = comparison_reports_dir / run_id
    report_dir.mkdir(parents=True, exist_ok=True)

    # Markdown report
    md_content = generate_markdown_report(comparison, config, initial_cash)
    md_path = report_dir / "comparison_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\nGenerated: {md_path}")

    # JSON data
    json_data = {
        "run_id": comparison["run_id"],
        "config": config,
        "shared_data_stats": comparison["shared_data_stats"],
        "total_duration": comparison["total_duration"],
        "personality_results": personality_results
    }
    json_path = report_dir / "comparison_data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    print(f"Generated: {json_path}")

    # CSV summary
    import csv
    csv_path = report_dir / "personality_summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Personality", "Total Return %", "Max Drawdown %", "Sharpe Ratio",
            "Trade Count", "Win Rate %", "Avg Position Days", "Avg Turnover Ratio",
            "Avg Cash Ratio", "Avg Gross Exposure", "Duration Sec", "Error Count"
        ])

        for personality, result in personality_results.items():
            win_rate = result.get('win_rate', 0)
            win_rate_pct = win_rate * 100 if win_rate <= 1 else win_rate
            metrics = result.get("metrics", {}) or {}
            writer.writerow([
                personality,
                f"{result.get('total_return', 0):.2f}",
                f"{result.get('max_drawdown', 0):.2f}",
                f"{result.get('sharpe_ratio', 0):.2f}",
                result.get('trade_count', 0),
                f"{win_rate_pct:.1f}",
                f"{result.get('avg_position_days', 0):.1f}",
                f"{float(metrics.get('avg_turnover_ratio', 0.0) or 0.0):.4f}",
                f"{float(metrics.get('avg_cash_ratio', 0.0) or 0.0):.4f}",
                f"{float(metrics.get('avg_gross_exposure', 0.0) or 0.0):.4f}",
                f"{result.get('duration_seconds', 0):.2f}",
                result.get('error_count', 0)
            ])
    print(f"Generated: {csv_path}")

    print("\nDone! All reports regenerated successfully.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python regenerate_comparison_report.py <run_id>")
        print("Example: python regenerate_comparison_report.py 20260224_072137")
        sys.exit(1)

    try:
        regenerate_report(sys.argv[1])
    except RegenerationError as e:
        print(f"Error: {e}")
        sys.exit(1)
