"""
Report Generator for Backtesting
=================================

Generates reports, charts, and CSV exports for backtest results.
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()
from shared.utils.run_id import generate_run_id

# Import token stats from deepfund
try:
    from llm.inference import get_token_stats
    TOKEN_STATS_AVAILABLE = True
except ImportError:
    TOKEN_STATS_AVAILABLE = False

# Import usage stats from deepear
try:
    from deepear.src.utils.stats import get_stats as get_deepear_stats
    DEEPEAR_STATS_AVAILABLE = True
except ImportError:
    DEEPEAR_STATS_AVAILABLE = False

try:
    from quantarena.benchmark_diagnostics import drain_benchmark_diagnostics
    BENCHMARK_DIAGNOSTICS_AVAILABLE = True
except ImportError:
    drain_benchmark_diagnostics = None
    BENCHMARK_DIAGNOSTICS_AVAILABLE = False


class ReportGenerator:
    """
    Generates backtest reports in various formats.

    Supports:
    - Markdown summary report
    - Equity curve chart (requires matplotlib)
    - Trade list CSV
    - Metrics JSON
    """

    def __init__(self, output_dir: str = "reports/backtest"):
        """
        Initialize report generator.

        Args:
            output_dir: Base directory for report outputs
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_run_id(self) -> str:
        """Generate a unique run ID for this backtest."""
        return generate_run_id()

    def generate_markdown(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None,
        token_stats_override: Optional[Dict] = None,
    ) -> str:
        """
        Generate a markdown report for backtest results.

        Args:
            result: BacktestResult object
            output_path: Optional path to save report

        Returns:
            Markdown report string
        """
        metrics = result.metrics
        tracker = result.tracker

        # Build report sections
        sections = []
        fof_config = getattr(result, "config", {}).get("fof", {}) if getattr(result, "config", None) else {}

        # Header
        sections.append(self._build_header(result))

        # Summary statistics
        sections.append(self._build_summary_section(metrics))

        # FOF overview
        if fof_config.get("daily_allocations"):
            sections.append(self._build_fof_overview_section(fof_config, tracker=tracker))

        # Performance metrics
        sections.append(self._build_metrics_section(metrics))

        # Behavior metrics
        sections.append(self._build_behavior_section(metrics))

        # Trade summary
        sections.append(self._build_trade_section(tracker))

        # Position summary
        sections.append(self._build_position_section(tracker))

        # FOF diagnostics
        if fof_config.get("daily_allocations"):
            sections.append(self._build_fof_section(fof_config, tracker=tracker))

        # Footer
        sections.append(self._build_footer(result, token_stats_override=token_stats_override))

        report = "\n\n".join(sections)

        # Save to file
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"Markdown report saved to {output_path}")

        return report

    def _build_header(self, result) -> str:
        """Build report header."""
        return f"""# Backtest Report

**Run ID:** {result.run_id}
**Period:** {result.start_date} to {result.end_date}
**Market:** {result.market.upper()}
**Tickers:** {', '.join(result.tickers)}
**Initial Capital:** ${result.initial_cash:,.2f}
"""

    def _build_summary_section(self, metrics: Dict) -> str:
        """Build summary statistics section."""
        rows = [
            "| **Initial Capital** | ${:,.2f} |".format(metrics.get("initial_cash", 0)),
            "| **Final Value** | ${:,.2f} |".format(metrics.get("final_value", 0)),
            "| **Total Return** | {:+.2f}% |".format(metrics.get("total_return", 0)),
            "| **Annualized Return** | {:+.2f}% |".format(metrics.get("annualized_return", 0)),
            "| **Trading Days** | {} |".format(metrics.get("trading_days", 0)),
        ]
        benchmark_source = str(metrics.get("benchmark_source", "unknown") or "unknown")
        benchmark_available = benchmark_source not in {"none", "unavailable", "unknown", ""}
        if benchmark_available and "benchmark_total_return" in metrics:
            rows.append(
                "| **Benchmark Return** | {:+.2f}% |".format(metrics.get("benchmark_total_return", 0))
            )
        if "benchmark_source" in metrics:
            rows.append("| **Benchmark Source** | {} |".format(benchmark_source))

        return "## Summary\n\n| Metric | Value |\n|--------|-------|\n" + "\n".join(rows) + "\n"

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Recursively replace non-finite floats with None for strict JSON output."""
        if isinstance(value, dict):
            return {key: ReportGenerator._json_safe(val) for key, val in value.items()}
        if isinstance(value, list):
            return [ReportGenerator._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [ReportGenerator._json_safe(item) for item in value]
        if isinstance(value, (np.generic,)):
            return ReportGenerator._json_safe(value.item())
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        return value

    @staticmethod
    def _extract_sleeve_names(sleeves: Any) -> list[str]:
        """Normalize configured sleeves into stable display names."""
        names: list[str] = []
        for sleeve in sleeves or []:
            if isinstance(sleeve, dict):
                name = str(sleeve.get("personality") or sleeve.get("name") or "").strip()
            else:
                name = str(sleeve).strip()
            if name:
                names.append(name)
        return names

    def _build_actual_position_weights(self, tracker, fallback_weights: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Build actual final holding weights from tracker summary when available."""
        fallback = dict(fallback_weights or {})
        if tracker is None or not hasattr(tracker, "get_summary"):
            return fallback

        summary = tracker.get_summary() or {}
        final_positions = summary.get("final_positions") or {}
        final_value = float(summary.get("final_value", 0.0) or 0.0)
        if final_value <= 0:
            final_cash = float(summary.get("final_cash", 0.0) or 0.0)
            position_value = sum(float((position or {}).get("value", 0.0) or 0.0) for position in final_positions.values())
            final_value = final_cash + position_value

        if final_value <= 0 or not final_positions:
            return fallback

        actual_weights: Dict[str, float] = {}
        for ticker, position in final_positions.items():
            value = float((position or {}).get("value", 0.0) or 0.0)
            if value <= 0:
                continue
            actual_weights[str(ticker)] = value / final_value
        return actual_weights or fallback

    def _select_latest_attribution_allocation(self, allocations: list[Dict[str, Any]]) -> Dict[str, Any]:
        """Prefer the latest completed attribution snapshot, fallback to the latest allocation."""
        for allocation in reversed(allocations or []):
            if allocation.get("attribution_complete"):
                return allocation
        return allocations[-1] if allocations else {}

    def _build_fof_overview_section(self, fof_config: Dict, tracker=None) -> str:
        """Build a compact FOF overview near the top of the report."""
        allocations = fof_config.get("daily_allocations", [])
        if not allocations:
            return ""

        latest = allocations[-1] if allocations else {}
        latest_stats = latest.get("rebalance_stats") or {}
        latest_regime = latest.get("regime", "unknown")
        latest_rationale = latest.get("rationale", "")
        rebalance_stat_items = [
            allocation.get("rebalance_stats", {}) or {}
            for allocation in allocations
            if allocation.get("rebalance_stats")
        ]
        turnover_ratios = [float(item.get("total_turnover_ratio", 0.0) or 0.0) for item in rebalance_stat_items]
        avg_total_turnover_ratio = sum(turnover_ratios) / len(turnover_ratios) if turnover_ratios else 0.0
        peak_total_turnover_ratio = max(turnover_ratios) if turnover_ratios else 0.0
        cumulative_executed_trades = sum(int(item.get("executed_trades", 0) or 0) for item in rebalance_stat_items)
        cumulative_skipped_trades = sum(int(item.get("skipped_trades", 0) or 0) for item in rebalance_stat_items)

        latest_sleeve_weights = latest.get("sleeve_weights") or {}
        top_sleeves = sorted(latest_sleeve_weights.items(), key=lambda item: item[1], reverse=True)[:3]
        latest_sleeve_mix = ", ".join(f"`{name}` {weight:.2%}" for name, weight in top_sleeves) or "`n/a` 0.00%"

        latest_top_positions = sorted(
            self._build_actual_position_weights(tracker, fallback_weights=latest.get("final_stock_weights") or {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
        latest_position_mix = ", ".join(f"`{ticker}` {weight:.2%}" for ticker, weight in latest_top_positions) or "`n/a` 0.00%"

        observed_sleeves = set(self._extract_sleeve_names(fof_config.get("sleeves", [])))
        for allocation in allocations:
            observed_sleeves.update((allocation.get("sleeve_weights") or {}).keys())
        sleeve_deviation_items = []
        for sleeve_name in sorted(observed_sleeves):
            history = [
                float((allocation.get("sleeve_weights") or {}).get(sleeve_name, 0.0) or 0.0)
                for allocation in allocations
            ]
            if not history:
                continue
            avg_weight = sum(history) / len(history)
            latest_weight = float(latest_sleeve_weights.get(sleeve_name, 0.0) or 0.0)
            sleeve_deviation_items.append((sleeve_name, latest_weight - avg_weight))
        sleeve_deviation_items.sort(key=lambda item: (-abs(item[1]), item[0]))
        if sleeve_deviation_items:
            top_sleeve_name, top_sleeve_deviation = sleeve_deviation_items[0]
            top_sleeve_deviation_text = f"`{top_sleeve_name}` {top_sleeve_deviation:+.2%}"
        else:
            top_sleeve_deviation_text = "`n/a` +0.00%"

        drift_alert_threshold = float(fof_config.get("sleeve_drift_alert_threshold", 0.05) or 0.05)
        latest_drift_alerts = 0
        if len(allocations) >= 2:
            prev_weights = allocations[-2].get("sleeve_weights") or {}
            for sleeve_name in sorted(set(prev_weights) | set(latest_sleeve_weights)):
                prev_weight = float(prev_weights.get(sleeve_name, 0.0) or 0.0)
                latest_weight = float(latest_sleeve_weights.get(sleeve_name, 0.0) or 0.0)
                if abs(latest_weight - prev_weight) + 1e-12 >= drift_alert_threshold:
                    latest_drift_alerts += 1

        latest_skip_reason_counts = latest_stats.get("skip_reason_counts", {}) or {}
        top_skip_reason = "n/a"
        top_skip_reason_count = 0
        if latest_skip_reason_counts:
            top_skip_reason, top_skip_reason_count = max(
                latest_skip_reason_counts.items(),
                key=lambda item: (item[1], item[0] == "weight_delta", item[0] == "trade_value_ratio", item[0] == "min_shares"),
            )
            if top_skip_reason_count <= 0:
                top_skip_reason = "n/a"

        latest_turnover_text = f"{float(latest_stats.get('total_turnover_ratio', 0.0) or 0.0):.2%}"
        turnover_profile_text = f"avg {avg_total_turnover_ratio:.2%} / peak {peak_total_turnover_ratio:.2%}"
        rebalance_activity_text = f"executed {cumulative_executed_trades}, skipped {cumulative_skipped_trades}"
        sleeve_signal_text = f"deviation {top_sleeve_deviation_text}; alerts {latest_drift_alerts} above {drift_alert_threshold:.2%}"
        skip_reason_text = f"`{top_skip_reason}` ({top_skip_reason_count})"

        rows = [
            f"| **Current State** | regime `{latest_regime}`, turnover {latest_turnover_text} |",
            f"| **Turnover Profile** | {turnover_profile_text} |",
            f"| **Rebalance Activity** | {rebalance_activity_text} |",
            f"| **Latest Sleeve Mix** | {latest_sleeve_mix} |",
            f"| **Latest Top Positions** | {latest_position_mix} |",
            f"| **Sleeve Signal** | {sleeve_signal_text} |",
            f"| **Latest Top Skip Reason** | {skip_reason_text} |",
        ]
        if latest_rationale:
            rows.append(f"| **Latest Rationale** | {latest_rationale} |")

        return "## FOF Overview\n\n| Item | Value |\n|------|-------|\n" + "\n".join(rows) + "\n\n"


    def _build_metrics_section(self, metrics: Dict) -> str:
        """Build performance metrics section."""
        rows = [
            "| **Sharpe Ratio** | {:.2f} |".format(metrics.get("sharpe_ratio", 0)),
            "| **Sortino Ratio** | {:.2f} |".format(metrics.get("sortino_ratio", 0)),
            "| **Max Drawdown** | {:.2f}% |".format(metrics.get("max_drawdown", 0)),
            "| **Max Drawdown Duration** | {} days |".format(metrics.get("max_drawdown_duration", 0)),
            "| **Volatility (Ann.)** | {:.2f}% |".format(metrics.get("volatility", 0)),
            "| **Win Rate** | {:.1f}% |".format(metrics.get("win_rate", 0)),
        ]
        if "excess_return" in metrics:
            rows.append("| **Excess Return (Ann.)** | {:+.2f}% |".format(metrics.get("excess_return", 0)))
        alpha = metrics.get("alpha")
        beta = metrics.get("beta")
        if alpha is not None and not pd.isna(alpha):
            rows.append("| **Alpha (Ann.)** | {:+.2f}% |".format(alpha))
        if beta is not None and not pd.isna(beta):
            rows.append("| **Beta** | {:.2f} |".format(beta))
        if "tracking_error" in metrics:
            rows.append("| **Tracking Error (Ann.)** | {:.2f}% |".format(metrics.get("tracking_error", 0)))
        if "information_ratio" in metrics:
            rows.append("| **Information Ratio** | {:.2f} |".format(metrics.get("information_ratio", 0)))
        if "calmar_ratio" in metrics:
            rows.append("| **Calmar Ratio** | {:.2f} |".format(metrics.get("calmar_ratio", 0)))
        if "cvar_95" in metrics:
            rows.append("| **CVaR (95%)** | {:.2f}% |".format(metrics.get("cvar_95", 0)))
        if "up_capture_ratio" in metrics:
            rows.append("| **Up Capture Ratio** | {:.2f} |".format(metrics.get("up_capture_ratio", 0)))
        if "down_capture_ratio" in metrics:
            rows.append("| **Down Capture Ratio** | {:.2f} |".format(metrics.get("down_capture_ratio", 0)))
        if "break_even_transaction_cost" in metrics:
            rows.append("| **Break-even TC (one-way)** | {:.4%} |".format(metrics.get("break_even_transaction_cost", 0)))

        return "## Performance Metrics\n\n| Metric | Value |\n|--------|-------|\n" + "\n".join(rows) + "\n"

    def _build_behavior_section(self, metrics: Dict) -> str:
        """Build behavior metrics section."""
        rows = []

        if "total_trades" in metrics:
            rows.append("| **Trade Count** | {} |".format(metrics.get("total_trades", 0)))
        if "avg_position_days" in metrics:
            rows.append("| **Avg Position Days** | {:.1f} |".format(metrics.get("avg_position_days", 0)))
        if "avg_turnover_ratio" in metrics:
            rows.append("| **Avg Turnover Ratio** | {:.2%} |".format(metrics.get("avg_turnover_ratio", 0)))
        if "peak_turnover_ratio" in metrics:
            rows.append("| **Peak Turnover Ratio** | {:.2%} |".format(metrics.get("peak_turnover_ratio", 0)))
        if "annualized_turnover_ratio" in metrics:
            rows.append("| **Annualized Turnover Ratio** | {:.2f}x |".format(metrics.get("annualized_turnover_ratio", 0)))
        if "avg_cash_ratio" in metrics:
            rows.append("| **Avg Cash Ratio** | {:.2%} |".format(metrics.get("avg_cash_ratio", 0)))
        if "avg_gross_exposure" in metrics:
            rows.append("| **Avg Gross Exposure** | {:.2%} |".format(metrics.get("avg_gross_exposure", 0)))
        if "value_filter_pass_rate" in metrics:
            rows.append("| **Value Filter Pass Rate** | {:.2f}% |".format(metrics.get("value_filter_pass_rate", 0)))
        if "value_consistency_score" in metrics:
            rows.append("| **Value Consistency Score** | {:.4f} |".format(metrics.get("value_consistency_score", 0)))
        if "vol_scaling_activation_rate" in metrics:
            rows.append("| **Vol Scaling Activation Rate** | {:.4f} |".format(metrics.get("vol_scaling_activation_rate", 0)))
        if "crash_breaker_trigger_count" in metrics:
            rows.append("| **Crash Breaker Trigger Count** | {:.0f} |".format(metrics.get("crash_breaker_trigger_count", 0)))
        if "avg_momentum_exposure_multiplier" in metrics:
            rows.append(
                "| **Avg Momentum Exposure Multiplier** | {:.4f} |".format(
                    metrics.get("avg_momentum_exposure_multiplier", 0)
                )
            )
        if "fof_rebalance_total_turnover_ratio" in metrics:
            rows.append(
                "| **FOF Rebalance Total Turnover** | {:.2%} |".format(
                    metrics.get("fof_rebalance_total_turnover_ratio", 0)
                )
            )

        if not rows:
            return ""

        return "## Behavior Metrics\n\n| Metric | Value |\n|--------|-------|\n" + "\n".join(rows) + "\n"


    @staticmethod
    def _compute_mcr_summary(allocations: list[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute sleeve-level marginal contribution to risk from FOF allocation history."""
        rows = []
        sleeve_weights_rows = []
        sleeve_return_rows = []
        attribution_dates = []
        for allocation in allocations or []:
            weights = allocation.get("sleeve_weights") or {}
            returns = allocation.get("sleeve_returns") or {}
            if not allocation.get("attribution_complete", True):
                continue
            if not weights or not returns:
                continue
            sleeve_weights_rows.append({str(k): float(v or 0.0) for k, v in weights.items()})
            sleeve_return_rows.append({str(k): float(v or 0.0) for k, v in returns.items()})
            attribution_dates.append(str(allocation.get("date") or ""))

        if len(sleeve_weights_rows) < 2 or len(sleeve_return_rows) < 2:
            return {"rows": [], "portfolio_volatility": 0.0}

        weights_df = pd.DataFrame(sleeve_weights_rows)
        returns_df = pd.DataFrame(sleeve_return_rows)
        common_cols = [col for col in weights_df.columns if col in returns_df.columns]
        if not common_cols:
            return {"rows": [], "portfolio_volatility": 0.0}

        weights_df = weights_df[common_cols]
        returns_df = returns_df[common_cols]
        combined = pd.concat(
            [
                pd.Series(attribution_dates, name="attribution_date"),
                weights_df.add_prefix("w_"),
                returns_df.add_prefix("r_"),
            ],
            axis=1,
        ).dropna()
        if len(combined) < 2:
            return {"rows": [], "portfolio_volatility": 0.0}

        weights_df = combined[[f"w_{col}" for col in common_cols]].rename(columns=lambda col: col[2:])
        returns_df = combined[[f"r_{col}" for col in common_cols]].rename(columns=lambda col: col[2:])
        covariance = returns_df.cov()
        latest_weights = weights_df.iloc[-1].astype(float)
        portfolio_variance = float(latest_weights.T @ covariance.values @ latest_weights)
        if portfolio_variance <= 0:
            return {"rows": [], "portfolio_volatility": 0.0}

        portfolio_volatility = portfolio_variance ** 0.5
        sigma_w = covariance.values @ latest_weights.values
        component_contrib = latest_weights.values * sigma_w / portfolio_volatility
        marginal_contrib = sigma_w / portfolio_volatility

        for idx, sleeve in enumerate(common_cols):
            rows.append(
                {
                    "sleeve": sleeve,
                    "latest_weight": float(latest_weights.iloc[idx]),
                    "mcr": float(marginal_contrib[idx]),
                    "component_contribution": float(component_contrib[idx]),
                }
            )

        rows.sort(key=lambda item: (-abs(item["component_contribution"]), item["sleeve"]))
        attribution_date = str(combined.iloc[-1]["attribution_date"]).strip() or None
        return {"rows": rows, "portfolio_volatility": portfolio_volatility, "attribution_date": attribution_date}

    def _build_fof_section(self, fof_config: Dict, tracker=None) -> str:
        """Build FOF diagnostics section when fund-of-funds mode is active."""
        sleeves = self._extract_sleeve_names(fof_config.get("sleeves", []))
        allocations = fof_config.get("daily_allocations", [])
        latest = allocations[-1] if allocations else {}
        attribution_latest = self._select_latest_attribution_allocation(allocations)
        regime = latest.get("regime", "unknown")

        sleeve_rows = []
        for sleeve, weight in sorted((latest.get("sleeve_weights") or {}).items()):
            sleeve_rows.append(f"| `{sleeve}` | {weight:.2%} |")
        if not sleeve_rows:
            sleeve_rows.append("| `n/a` | 0.00% |")

        top_positions = sorted(
            self._build_actual_position_weights(tracker, fallback_weights=latest.get("final_stock_weights") or {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
        position_rows = []
        for ticker, weight in top_positions:
            position_rows.append(f"| `{ticker}` | {weight:.2%} |")
        if not position_rows:
            position_rows.append("| `n/a` | 0.00% |")

        regime_counts: Dict[str, int] = {}
        for allocation in allocations:
            key = str(allocation.get("regime", "unknown"))
            regime_counts[key] = regime_counts.get(key, 0) + 1
        regime_summary = ", ".join(f"{key}: {value}" for key, value in sorted(regime_counts.items())) or "n/a"
        rationale = latest.get("rationale", "")
        contribution_rows = []
        for sleeve, contribution in sorted((attribution_latest.get("sleeve_contributions") or {}).items()):
            sleeve_return = (attribution_latest.get("sleeve_returns") or {}).get(sleeve, 0.0)
            contribution_rows.append(
                f"| `{sleeve}` | {sleeve_return:+.2%} | {contribution:+.2%} |"
            )
        if not contribution_rows:
            contribution_rows.append("| `n/a` | +0.00% | +0.00% |")

        attribution_snapshot_date = attribution_latest.get("date", "n/a")
        estimated_total_contribution = attribution_latest.get("estimated_total_contribution")
        total_contribution_line = f"**Attribution Snapshot Date:** {attribution_snapshot_date}\n\n"
        if estimated_total_contribution is not None:
            total_contribution_line += (
                f"**Estimated Total Contribution:** {estimated_total_contribution:+.2%}\n\n"
            )

        mcr_summary = self._compute_mcr_summary(allocations)
        mcr_rows = []
        for item in mcr_summary.get("rows", []):
            mcr_rows.append(
                f"| `{item['sleeve']}` | {item['latest_weight']:.2%} | {item['mcr']:.4f} | {item['component_contribution']:.4f} |"
            )
        if not mcr_rows:
            mcr_rows.append("| `n/a` | 0.00% | 0.0000 | 0.0000 |")
        mcr_date = mcr_summary.get("attribution_date") or "n/a"
        mcr_section = (
            "### Sleeve Risk Contribution (MCR)\n\n"
            f"**Attribution Date:** {mcr_date}  \n"
            f"**Portfolio Volatility (daily):** {float(mcr_summary.get('portfolio_volatility', 0.0) or 0.0):.4f}  \n\n"
            "| Sleeve | Attributed Weight | MCR | Component Contribution |\n"
            "|--------|-------------------|-----|------------------------|\n"
            + "\n".join(mcr_rows)
            + "\n\n"
        )

        rebalance_stats = latest.get("rebalance_stats") or {}
        skip_reason_counts = rebalance_stats.get("skip_reason_counts", {}) or {}
        rebalance_stat_items = [
            allocation.get("rebalance_stats", {}) or {}
            for allocation in allocations
            if allocation.get("rebalance_stats")
        ]
        cumulative_executed_trades = sum(int(item.get("executed_trades", 0) or 0) for item in rebalance_stat_items)
        cumulative_skipped_trades = sum(int(item.get("skipped_trades", 0) or 0) for item in rebalance_stat_items)
        cumulative_executed_trade_value = sum(float(item.get("executed_trade_value", 0.0) or 0.0) for item in rebalance_stat_items)
        cumulative_skipped_trade_value = sum(float(item.get("skipped_trade_value", 0.0) or 0.0) for item in rebalance_stat_items)
        turnover_ratios = [float(item.get("total_turnover_ratio", 0.0) or 0.0) for item in rebalance_stat_items]
        avg_total_turnover_ratio = sum(turnover_ratios) / len(turnover_ratios) if turnover_ratios else 0.0
        peak_total_turnover_ratio = max(turnover_ratios) if turnover_ratios else 0.0
        cumulative_rebalance_section = (
            "### Cumulative Rebalance Summary\n\n"
            f"**Executed Trades:** {cumulative_executed_trades}  \n"
            f"**Skipped Trades:** {cumulative_skipped_trades}  \n"
            f"**Executed Trade Value:** {cumulative_executed_trade_value:.2f}  \n"
            f"**Skipped Trade Value:** {cumulative_skipped_trade_value:.2f}  \n"
            f"**Avg Total Turnover Ratio:** {avg_total_turnover_ratio:.2%}  \n"
            f"**Peak Total Turnover Ratio:** {peak_total_turnover_ratio:.2%}\n\n"
        )
        regime_turnover_rows = []
        regime_turnover_buckets: Dict[str, Dict[str, Any]] = {}
        regime_skip_reason_rows = []
        reason_labels = {
            "weight_delta": "weight_delta",
            "trade_value_ratio": "trade_value_ratio",
            "min_shares": "min_shares",
        }
        for allocation in allocations:
            stats = allocation.get("rebalance_stats", {}) or {}
            if not stats:
                continue
            regime_key = str(allocation.get("regime", "unknown"))
            bucket = regime_turnover_buckets.setdefault(
                regime_key,
                {
                    "days": 0,
                    "executed_trades": 0,
                    "skipped_trades": 0,
                    "turnover_ratios": [],
                    "skip_reason_counts": {"weight_delta": 0, "trade_value_ratio": 0, "min_shares": 0},
                },
            )
            bucket["days"] += 1
            bucket["executed_trades"] += int(stats.get("executed_trades", 0) or 0)
            bucket["skipped_trades"] += int(stats.get("skipped_trades", 0) or 0)
            bucket["turnover_ratios"].append(float(stats.get("total_turnover_ratio", 0.0) or 0.0))
            skip_reason_counts_item = stats.get("skip_reason_counts", {}) or {}
            for reason_key in bucket["skip_reason_counts"]:
                bucket["skip_reason_counts"][reason_key] += int(skip_reason_counts_item.get(reason_key, 0) or 0)
        for regime_key, bucket in sorted(regime_turnover_buckets.items()):
            turnover_values = bucket.get("turnover_ratios", [])
            avg_turnover = sum(turnover_values) / len(turnover_values) if turnover_values else 0.0
            peak_turnover = max(turnover_values) if turnover_values else 0.0
            regime_turnover_rows.append(
                f"| `{regime_key}` | {bucket['days']} | {bucket['executed_trades']} | {bucket['skipped_trades']} | {avg_turnover:.2%} | {peak_turnover:.2%} |"
            )
            skip_reason_counts_bucket = bucket.get("skip_reason_counts", {}) or {}
            top_reason_key, top_reason_count = max(
                skip_reason_counts_bucket.items(),
                key=lambda item: (item[1], item[0] == "weight_delta", item[0] == "trade_value_ratio", item[0] == "min_shares"),
            ) if skip_reason_counts_bucket else ("weight_delta", 0)
            top_reason_label = reason_labels.get(top_reason_key, top_reason_key) if top_reason_count > 0 else "n/a"
            regime_skip_reason_rows.append(
                f"| `{regime_key}` | {bucket['skipped_trades']} | `{top_reason_label}` | {top_reason_count} |"
            )
        if not regime_turnover_rows:
            regime_turnover_rows.append("| `n/a` | 0 | 0 | 0 | 0.00% | 0.00% |")
        if not regime_skip_reason_rows:
            regime_skip_reason_rows.append("| `n/a` | 0 | `n/a` | 0 |")
        regime_turnover_section = (
            "### Regime Turnover Summary\n\n"
            "| Regime | Days | Executed Trades | Skipped Trades | Avg Total Turnover | Peak Total Turnover |\n"
            "|--------|------|-----------------|----------------|--------------------|---------------------|\n"
            + "\n".join(regime_turnover_rows)
            + "\n\n"
        )
        regime_skip_reason_section = (
            "### Regime Skip Reason Summary\n\n"
            "| Regime | Skipped Trades | Top Skip Reason | Top Reason Count |\n"
            "|--------|----------------|-----------------|------------------|\n"
            + "\n".join(regime_skip_reason_rows)
            + "\n\n"
        )
        observed_sleeves = set(sleeves)
        for allocation in allocations:
            observed_sleeves.update((allocation.get("sleeve_weights") or {}).keys())
        sleeve_stability_rows = []
        for sleeve_name in sorted(observed_sleeves):
            history = [
                float((allocation.get("sleeve_weights") or {}).get(sleeve_name, 0.0) or 0.0)
                for allocation in allocations
            ]
            if not history:
                continue
            avg_weight = sum(history) / len(history)
            min_weight = min(history)
            max_weight = max(history)
            max_daily_change = 0.0
            for prev_weight, next_weight in zip(history, history[1:]):
                max_daily_change = max(max_daily_change, abs(next_weight - prev_weight))
            sleeve_stability_rows.append(
                f"| `{sleeve_name}` | {avg_weight:.2%} | {min_weight:.2%} | {max_weight:.2%} | {max_daily_change:.2%} |"
            )
        if not sleeve_stability_rows:
            sleeve_stability_rows.append("| `n/a` | 0.00% | 0.00% | 0.00% | 0.00% |")
        sleeve_stability_section = (
            "### Sleeve Stability Summary\n\n"
            "| Sleeve | Avg Weight | Min Weight | Max Weight | Max Daily Change |\n"
            "|--------|------------|------------|------------|------------------|\n"
            + "\n".join(sleeve_stability_rows)
            + "\n\n"
        )
        sleeve_deviation_items = []
        latest_sleeve_weights = latest.get("sleeve_weights") or {}
        for sleeve_name in sorted(observed_sleeves):
            history = [
                float((allocation.get("sleeve_weights") or {}).get(sleeve_name, 0.0) or 0.0)
                for allocation in allocations
            ]
            if not history:
                continue
            avg_weight = sum(history) / len(history)
            latest_weight = float(latest_sleeve_weights.get(sleeve_name, 0.0) or 0.0)
            deviation = latest_weight - avg_weight
            sleeve_deviation_items.append((sleeve_name, latest_weight, avg_weight, deviation))
        sleeve_deviation_items.sort(key=lambda item: (-abs(item[3]), item[0]))
        sleeve_deviation_rows = [
            f"| `{sleeve_name}` | {latest_weight:.2%} | {avg_weight:.2%} | {deviation:+.2%} | {abs(deviation):.2%} |"
            for sleeve_name, latest_weight, avg_weight, deviation in sleeve_deviation_items
        ]
        if not sleeve_deviation_rows:
            sleeve_deviation_rows.append("| `n/a` | 0.00% | 0.00% | +0.00% | 0.00% |")
        sleeve_deviation_section = (
            "### Latest Vs Avg Sleeve Deviation\n\n"
            "| Sleeve | Latest Weight | Avg Weight | Deviation | Abs Deviation |\n"
            "|--------|---------------|------------|-----------|---------------|\n"
            + "\n".join(sleeve_deviation_rows)
            + "\n\n"
        )
        drift_alert_threshold = float(fof_config.get("sleeve_drift_alert_threshold", 0.05) or 0.05)
        drift_alert_rows = []
        for prev_allocation, next_allocation in zip(allocations, allocations[1:]):
            prev_weights = prev_allocation.get("sleeve_weights") or {}
            next_weights = next_allocation.get("sleeve_weights") or {}
            for sleeve_name in sorted(set(prev_weights) | set(next_weights)):
                prev_weight = float(prev_weights.get(sleeve_name, 0.0) or 0.0)
                next_weight = float(next_weights.get(sleeve_name, 0.0) or 0.0)
                delta = next_weight - prev_weight
                if abs(delta) + 1e-12 >= drift_alert_threshold:
                    drift_alert_rows.append(
                        f"| {next_allocation.get('date', 'n/a')} | `{sleeve_name}` | {prev_weight:.2%} | {next_weight:.2%} | {delta:+.2%} |"
                    )
        if drift_alert_rows:
            sleeve_drift_alert_section = (
                "### Sleeve Drift Alerts\n\n"
                f"**Threshold:** {drift_alert_threshold:.2%}\n\n"
                "| Date | Sleeve | Previous Weight | Current Weight | Change |\n"
                "|------|--------|-----------------|----------------|--------|\n"
                + "\n".join(drift_alert_rows)
                + "\n\n"
            )
        else:
            sleeve_drift_alert_section = (
                "### Sleeve Drift Alerts\n\n"
                f"No sleeve drift alerts above {drift_alert_threshold:.2%}.\n\n"
            )
        rebalance_stats_section = (
            "### Latest Rebalance Stats\n\n"
            f"**Executed Trades:** {int(rebalance_stats.get('executed_trades', 0) or 0)}  \n"
            f"**Skipped Trades:** {int(rebalance_stats.get('skipped_trades', 0) or 0)}  \n"
            f"**Executed Trade Value:** {float(rebalance_stats.get('executed_trade_value', 0.0) or 0.0):.2f}  \n"
            f"**Skipped Trade Value:** {float(rebalance_stats.get('skipped_trade_value', 0.0) or 0.0):.2f}  \n"
            f"**Executed Turnover Ratio:** {float(rebalance_stats.get('executed_turnover_ratio', 0.0) or 0.0):.2%}  \n"
            f"**Skipped Turnover Ratio:** {float(rebalance_stats.get('skipped_turnover_ratio', 0.0) or 0.0):.2%}  \n"
            f"**Total Turnover Ratio:** {float(rebalance_stats.get('total_turnover_ratio', 0.0) or 0.0):.2%}  \n"
            f"**Skip - Weight Delta:** {int(skip_reason_counts.get('weight_delta', 0) or 0)}  \n"
            f"**Skip - Trade Value Ratio:** {int(skip_reason_counts.get('trade_value_ratio', 0) or 0)}  \n"
            f"**Skip - Min Shares:** {int(skip_reason_counts.get('min_shares', 0) or 0)}\n\n"
        )

        consensus = latest.get("sleeve_consensus") or {}
        consensus_rows = []
        for item in consensus.get("top_tickers", []) or []:
            consensus_rows.append(
                "| `{ticker}` | {support_count} | {support_ratio:.0%} | {average_weight:.2%} |".format(
                    ticker=item.get("ticker", "n/a"),
                    support_count=item.get("support_count", 0),
                    support_ratio=float(item.get("support_ratio", 0.0) or 0.0),
                    average_weight=float(item.get("average_weight", 0.0) or 0.0),
                )
            )
        if not consensus_rows:
            consensus_rows.append("| `n/a` | 0 | 0% | 0.00% |")
        consensus_section = (
            "### Latest Sleeve Consensus\n\n"
            f"**Average Pairwise Overlap:** {float(consensus.get('average_pairwise_overlap', 0.0) or 0.0):.2%}  \n"
            f"**Distinct Sleeve Tickers:** {int(consensus.get('distinct_ticker_count', 0) or 0)}\n\n"
            "| Ticker | Supporting Sleeves | Support Ratio | Avg Sleeve Weight |\n"
            "|--------|--------------------|---------------|-------------------|\n"
            + "\n".join(consensus_rows)
            + "\n\n"
        )

        sleeve_composition_blocks = []
        for sleeve, targets in sorted((latest.get("sleeve_target_weights") or {}).items()):
            top_targets = sorted((targets or {}).items(), key=lambda item: item[1], reverse=True)[:3]
            if top_targets:
                target_summary = ", ".join(f"`{ticker}` {weight:.2%}" for ticker, weight in top_targets)
            else:
                target_summary = "`n/a` 0.00%"
            sleeve_composition_blocks.append(f"- `{sleeve}`: {target_summary}")
        sleeve_composition_section = ""
        if sleeve_composition_blocks:
            sleeve_composition_section = (
                "### Latest Sleeve Top Holdings\n\n"
                + "\n".join(sleeve_composition_blocks)
                + "\n\n"
            )

        return (
            "## FOF Diagnostics\n\n"
            f"**Sleeves:** {', '.join(sleeves) if sleeves else 'n/a'}  \n"
            f"**Latest Regime:** `{regime}`  \n"
            f"**Regime Counts:** {regime_summary}  \n"
            f"**Latest Rationale:** {rationale}\n\n"
            "### Latest Sleeve Weights\n\n"
            "| Sleeve | Weight |\n|--------|--------|\n"
            + "\n".join(sleeve_rows)
            + "\n\n### Latest Sleeve Attribution\n\n"
            "| Sleeve | Sleeve Return | Weighted Contribution |\n"
            "|--------|---------------|-----------------------|\n"
            + "\n".join(contribution_rows)
            + "\n\n"
            + total_contribution_line
            + mcr_section
            + cumulative_rebalance_section
            + regime_turnover_section
            + regime_skip_reason_section
            + sleeve_stability_section
            + sleeve_deviation_section
            + sleeve_drift_alert_section
            + rebalance_stats_section
            + consensus_section
            + sleeve_composition_section
            + "### Latest Top Positions\n\n| Ticker | Weight |\n|--------|--------|\n"
            + "\n".join(position_rows)
            + "\n"
        )

    def _build_trade_section(self, tracker) -> str:
        """Build trade summary section."""
        trades = tracker.get_trades()
        buy_count = tracker.get_buy_count()
        sell_count = tracker.get_sell_count()

        section = f"""## Trade Summary

- **Total Trades:** {len(trades)}
- **Buy Orders:** {buy_count}
- **Sell Orders:** {sell_count}

"""

        if trades:
            section += "### Trade Log\n\n"
            section += "| Date | Ticker | Action | Shares | Price | Value |\n"
            section += "|------|--------|--------|--------|-------|-------|\n"

            for trade in trades[:50]:  # Limit to 50 most recent
                section += f"| {trade.date} | {trade.ticker} | {trade.action} | {trade.shares} | ${trade.price:.2f} | ${trade.value:,.2f} |\n"

            if len(trades) > 50:
                section += f"\n*...and {len(trades) - 50} more trades*\n"

        return section

    def _build_position_section(self, tracker) -> str:
        """Build final position section."""
        positions = tracker.get_position_summary()
        summary = tracker.get_summary()

        section = "## Final Positions\n\n"

        if positions:
            section += "| Ticker | Shares | Value |\n"
            section += "|--------|--------|-------|\n"

            for ticker, pos in positions.items():
                shares = pos.get('shares', 0)
                value = pos.get('value', 0)
                if shares > 0:
                    section += f"| {ticker} | {shares} | ${value:,.2f} |\n"
        else:
            section += "No open positions.\n"

        section += f"\n**Cash Balance:** ${summary.get('final_cash', 0):,.2f}\n"

        return section

    def _build_footer(self, result, token_stats_override: Optional[Dict] = None) -> str:
        """Build report footer."""
        footer = "---\n\n"

        # Add token usage section if available
        token_stats = token_stats_override
        if token_stats is None and TOKEN_STATS_AVAILABLE:
            token_stats = get_token_stats()
        if token_stats and token_stats.get("calls", 0) > 0:
            footer += self._build_token_section(token_stats)

        footer += f"""*Report generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Backtest Framework v1.0*
"""
        return footer

    def _build_token_section(self, token_stats: Dict) -> str:
        """Build token usage section."""
        total_input = token_stats.get("total_input", 0)
        total_output = token_stats.get("total_output", 0)
        total_tokens = total_input + total_output
        calls = token_stats.get("calls", 0)

        # DeepSeek pricing: ¥1/million input, ¥2/million output
        input_cost = total_input / 1_000_000 * 1
        output_cost = total_output / 1_000_000 * 2
        total_cost = input_cost + output_cost

        section = f"""## Token Usage & Cost

| Metric | Value |
|--------|-------|
| **Total Calls** | {calls} |
| **Input Tokens** | {total_input:,} |
| **Output Tokens** | {total_output:,} |
| **Total Tokens** | {total_tokens:,} |
| **Estimated Cost** | ¥{total_cost:.4f} |

### By Agent

| Agent | Calls | Input | Output |
|-------|-------|-------|--------|
"""
        by_agent = token_stats.get("by_agent", {})
        for agent, stats in by_agent.items():
            section += f"| {agent} | {stats.get('calls', 0)} | {stats.get('input', 0):,} | {stats.get('output', 0):,} |\n"

        section += "\n"

        # Add API call statistics from deepear if available
        if DEEPEAR_STATS_AVAILABLE:
            try:
                deepear_stats = get_deepear_stats()
                summary = deepear_stats.get_summary()
                api_calls = summary.get('api_calls', {})

                if api_calls.get('total', 0) > 0:
                    section += """### API Calls

| API | Calls | Success | Failed | Avg Time |
|-----|-------|---------|--------|----------|
"""
                    for category, stats in api_calls.get('by_category', {}).items():
                        avg_time = f"{stats.get('avg_time_ms', 0):.0f}ms"
                        section += f"| {category} | {stats.get('count', 0)} | {stats.get('success', 0)} | {stats.get('failed', 0)} | {avg_time} |\n"
                    section += "\n"
            except Exception:
                pass

        return section

    def generate_equity_curve_chart(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate equity curve chart.

        Args:
            result: BacktestResult object
            output_path: Optional path to save chart

        Returns:
            Path to saved chart or None if matplotlib unavailable
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            logger.warning("matplotlib not available, skipping chart generation")
            return None

        equity_curve = result.tracker.get_equity_curve()

        if equity_curve.empty:
            logger.warning("No equity curve data to plot")
            return None

        benchmark_curve = getattr(result, "benchmark_curve", None)
        benchmark_df = pd.DataFrame()
        if isinstance(benchmark_curve, pd.Series) and not benchmark_curve.empty:
            benchmark_df = benchmark_curve.copy().rename("benchmark_value").reset_index()
            benchmark_df = benchmark_df.rename(columns={benchmark_df.columns[0]: "date"})
            benchmark_df["date"] = pd.to_datetime(benchmark_df["date"])
            benchmark_df = benchmark_df.sort_values("date")

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

        # Plot 1: Equity curve
        ax1.plot(equity_curve['date'], equity_curve['total_value'], 'b-', linewidth=1.5, label='Portfolio')
        if not benchmark_df.empty:
            ax1.plot(
                benchmark_df["date"],
                benchmark_df["benchmark_value"],
                linestyle="--",
                color="black",
                linewidth=1.3,
                label=f"Benchmark ({getattr(result, 'benchmark_source', 'index')})",
            )
        ax1.axhline(y=result.initial_cash, color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
        ax1.fill_between(equity_curve['date'], result.initial_cash, equity_curve['total_value'],
                         where=equity_curve['total_value'] >= result.initial_cash,
                         color='green', alpha=0.3)
        ax1.fill_between(equity_curve['date'], result.initial_cash, equity_curve['total_value'],
                         where=equity_curve['total_value'] < result.initial_cash,
                         color='red', alpha=0.3)
        ax1.set_ylabel('Portfolio Value ($)')
        ax1.set_title(f'Equity Curve - {result.run_id}')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Plot 2: Daily returns
        colors = ['green' if r >= 0 else 'red' for r in equity_curve['daily_return']]
        ax2.bar(equity_curve['date'], equity_curve['daily_return'], color=colors, alpha=0.7, label='Portfolio Daily')
        if not benchmark_df.empty:
            merged = equity_curve.merge(benchmark_df, on="date", how="left")
            merged["benchmark_daily"] = merged["benchmark_value"].pct_change().fillna(0.0) * 100
            ax2.plot(
                merged["date"],
                merged["benchmark_daily"],
                color="black",
                linestyle="--",
                linewidth=1.0,
                label="Benchmark Daily",
            )
        ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax2.set_ylabel('Daily Return (%)')
        ax2.set_xlabel('Date')
        ax2.grid(True, alpha=0.3)
        ax2.legend()

        # Format x-axis
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.xticks(rotation=45)

        plt.tight_layout()

        # Save to file
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            logger.info(f"Equity curve chart saved to {output_path}")
            plt.close()
            return output_path
        else:
            plt.close()
            return None

    def generate_trades_csv(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None
    ) -> str:
        """
        Generate trades CSV file.

        Args:
            result: BacktestResult object
            output_path: Optional path to save CSV

        Returns:
            CSV content as string
        """
        trades_df = result.tracker.get_trades_df()

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            trades_df.to_csv(output_path, index=False)
            logger.info(f"Trades CSV saved to {output_path}")

        return trades_df.to_csv(index=False)

    def generate_metrics_json(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None
    ) -> str:
        """
        Generate metrics JSON file.

        Args:
            result: BacktestResult object
            output_path: Optional path to save JSON

        Returns:
            JSON content as string
        """
        data = {
            "run_id": result.run_id,
            "start_date": result.start_date,
            "end_date": result.end_date,
            "market": result.market,
            "tickers": result.tickers,
            "initial_cash": result.initial_cash,
            "metrics": result.metrics,
            "summary": result.tracker.get_summary(),
            "config": getattr(result, "config", {}),
        }

        json_str = json.dumps(self._json_safe(data), indent=2, allow_nan=False, default=str)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(json_str)
            logger.info(f"Metrics JSON saved to {output_path}")

        return json_str

    # Estimated DeepSeek pricing (CNY per 1M tokens); mirrors engine.finalize_run.
    COST_CNY_PER_M_INPUT = 1.0
    COST_CNY_PER_M_OUTPUT = 2.0

    @staticmethod
    def _git_revision() -> Dict[str, Any]:
        """Best-effort git provenance; never fails the report.

        SHA and dirty-state are probed independently so a slow `git status`
        (e.g. large untracked data dirs) cannot discard an available SHA.
        """
        import subprocess

        repo_root = Path(__file__).resolve().parents[1]
        sha: Optional[str] = None
        dirty: Optional[bool] = None
        try:
            probe = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root, capture_output=True, text=True, timeout=5,
            )
            sha = probe.stdout.strip() or None if probe.returncode == 0 else None
        except Exception:
            sha = None
        if sha:
            try:
                status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=repo_root, capture_output=True, text=True, timeout=5,
                )
                if status.returncode == 0:
                    dirty = bool(status.stdout.strip())
            except Exception:
                dirty = None
        return {"sha": sha, "dirty": dirty}

    def generate_run_manifest(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None,
        token_stats_override: Optional[Dict] = None,
    ) -> str:
        """Generate a run manifest tying the run to its inputs and LLM spend.

        Captures git provenance, the experiment definition, and aggregated
        token usage/cost so mandate sweeps can be audited and budgeted.
        """
        config = getattr(result, "config", {}) or {}

        token_stats = token_stats_override
        if token_stats is None and TOKEN_STATS_AVAILABLE:
            token_stats = get_token_stats()
        token_stats = token_stats or {}

        total_input = int(token_stats.get("total_input", 0) or 0)
        total_output = int(token_stats.get("total_output", 0) or 0)
        llm_usage = {
            "calls": int(token_stats.get("calls", 0) or 0),
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "estimated_cost_cny": round(
                total_input / 1_000_000 * self.COST_CNY_PER_M_INPUT
                + total_output / 1_000_000 * self.COST_CNY_PER_M_OUTPUT,
                4,
            ),
            "by_agent": token_stats.get("by_agent", {}),
        }

        # getattr defaults keep the manifest resilient to partially-populated
        # results (several report tests drive this path with lean stubs).
        data = {
            "manifest_version": 1,
            "run_id": getattr(result, "run_id", None),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "git": self._git_revision(),
            "experiment": {
                "market": getattr(result, "market", None),
                "tickers": getattr(result, "tickers", None),
                "start_date": getattr(result, "start_date", None),
                "end_date": getattr(result, "end_date", None),
                "initial_cash": getattr(result, "initial_cash", None),
                "personality": config.get("personality"),
                "workflow_analysts": config.get("workflow_analysts"),
                "llm": config.get("llm"),
                "api_source": config.get("api_source"),
                "benchmark_source": getattr(result, "benchmark_source", None),
            },
            "llm_usage": llm_usage,
            "errors": list(getattr(result, "errors", []) or []),
        }

        json_str = json.dumps(self._json_safe(data), indent=2, allow_nan=False, default=str)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            logger.info(f"Run manifest saved to {output_path}")

        return json_str

    def generate_broker_audit_jsonl(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None,
    ) -> str:
        """Generate a JSONL paper broker audit trail."""
        events = getattr(result, "broker_audit_events", []) or []
        lines = [
            json.dumps(self._json_safe(event), allow_nan=False, default=str)
            for event in events
        ]
        jsonl_str = "\n".join(lines)
        if lines:
            jsonl_str += "\n"

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(jsonl_str)
            logger.info(f"Broker audit JSONL saved to {output_path}")

        return jsonl_str

    def generate_benchmark_diagnostics_jsonl(self, output_path: Optional[str] = None) -> str:
        """Generate benchmark provider diagnostics JSONL."""
        records = []
        if BENCHMARK_DIAGNOSTICS_AVAILABLE and drain_benchmark_diagnostics is not None:
            records = [self._json_safe(record) for record in drain_benchmark_diagnostics()]
        lines = [
            json.dumps(record, allow_nan=False, default=str, sort_keys=True)
            for record in records
        ]
        jsonl_str = "\n".join(lines)
        if lines:
            jsonl_str += "\n"

        if output_path and lines:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(jsonl_str)
            logger.info(f"Benchmark diagnostics JSONL saved to {output_path}")

        return jsonl_str

    def generate_fof_allocations_json(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None
    ) -> str:
        """Generate FOF daily allocation JSON when available."""
        allocations = (getattr(result, "config", {}) or {}).get("fof", {}).get("daily_allocations", [])
        data = {
            "run_id": getattr(result, "run_id", ""),
            "personality": (getattr(result, "config", {}) or {}).get("personality", ""),
            "sleeves": (getattr(result, "config", {}) or {}).get("fof", {}).get("sleeves", []),
            "daily_allocations": allocations,
        }
        json_str = json.dumps(self._json_safe(data), indent=2, allow_nan=False, default=str)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            logger.info(f"FOF allocations JSON saved to {output_path}")

        return json_str

    def generate_fof_allocations_csv(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None
    ) -> str:
        """Generate flattened FOF daily allocation CSV when available."""
        allocations = (getattr(result, "config", {}) or {}).get("fof", {}).get("daily_allocations", [])
        rows = []
        for allocation in allocations:
            date = allocation.get("date")
            regime = allocation.get("regime")
            rationale = allocation.get("rationale", "")
            attribution_complete = bool(allocation.get("attribution_complete", True))
            sleeve_weights = allocation.get("sleeve_weights", {}) or {}
            sleeve_returns = allocation.get("sleeve_returns", {}) or {}
            sleeve_contributions = allocation.get("sleeve_contributions", {}) or {}
            sleeve_target_weights = allocation.get("sleeve_target_weights", {}) or {}
            consensus = allocation.get("sleeve_consensus", {}) or {}
            rebalance_stats = allocation.get("rebalance_stats", {}) or {}
            skip_reason_counts = rebalance_stats.get("skip_reason_counts", {}) or {}
            final_stock_weights = allocation.get("final_stock_weights", {}) or {}
            for sleeve, weight in sorted(sleeve_weights.items()):
                rows.append({
                    "date": date,
                    "regime": regime,
                    "entry_type": "sleeve",
                    "sleeve": sleeve,
                    "name": sleeve,
                    "weight": weight,
                    "sleeve_return": sleeve_returns.get(sleeve) if attribution_complete else None,
                    "weighted_contribution": sleeve_contributions.get(sleeve) if attribution_complete else None,
                    "support_count": None,
                    "support_ratio": None,
                    "average_sleeve_weight": None,
                    "executed_trades": rebalance_stats.get("executed_trades"),
                    "skipped_trades": rebalance_stats.get("skipped_trades"),
                    "executed_trade_value": rebalance_stats.get("executed_trade_value"),
                    "skipped_trade_value": rebalance_stats.get("skipped_trade_value"),
                    "executed_turnover_ratio": rebalance_stats.get("executed_turnover_ratio"),
                    "skipped_turnover_ratio": rebalance_stats.get("skipped_turnover_ratio"),
                    "total_turnover_ratio": rebalance_stats.get("total_turnover_ratio"),
                    "skipped_weight_delta_trades": skip_reason_counts.get("weight_delta"),
                    "skipped_trade_value_ratio_trades": skip_reason_counts.get("trade_value_ratio"),
                    "skipped_min_shares_trades": skip_reason_counts.get("min_shares"),
                    "rationale": rationale,
                })
            for sleeve, targets in sorted(sleeve_target_weights.items()):
                for ticker, weight in sorted((targets or {}).items()):
                    rows.append({
                        "date": date,
                        "regime": regime,
                        "entry_type": "sleeve_ticker",
                        "sleeve": sleeve,
                        "name": ticker,
                        "weight": weight,
                        "sleeve_return": sleeve_returns.get(sleeve) if attribution_complete else None,
                        "weighted_contribution": sleeve_contributions.get(sleeve) if attribution_complete else None,
                        "support_count": None,
                        "support_ratio": None,
                        "average_sleeve_weight": None,
                        "executed_trades": rebalance_stats.get("executed_trades"),
                        "skipped_trades": rebalance_stats.get("skipped_trades"),
                        "executed_trade_value": rebalance_stats.get("executed_trade_value"),
                        "skipped_trade_value": rebalance_stats.get("skipped_trade_value"),
                        "executed_turnover_ratio": rebalance_stats.get("executed_turnover_ratio"),
                        "skipped_turnover_ratio": rebalance_stats.get("skipped_turnover_ratio"),
                        "total_turnover_ratio": rebalance_stats.get("total_turnover_ratio"),
                        "skipped_weight_delta_trades": skip_reason_counts.get("weight_delta"),
                        "skipped_trade_value_ratio_trades": skip_reason_counts.get("trade_value_ratio"),
                        "skipped_min_shares_trades": skip_reason_counts.get("min_shares"),
                        "rationale": rationale,
                    })
            for item in consensus.get("top_tickers", []) or []:
                rows.append({
                    "date": date,
                    "regime": regime,
                    "entry_type": "consensus_ticker",
                    "sleeve": None,
                    "name": item.get("ticker"),
                    "weight": item.get("aggregate_weight"),
                    "sleeve_return": None,
                    "weighted_contribution": None,
                    "support_count": item.get("support_count"),
                    "support_ratio": item.get("support_ratio"),
                    "average_sleeve_weight": item.get("average_weight"),
                    "executed_trades": rebalance_stats.get("executed_trades"),
                    "skipped_trades": rebalance_stats.get("skipped_trades"),
                    "executed_trade_value": rebalance_stats.get("executed_trade_value"),
                    "skipped_trade_value": rebalance_stats.get("skipped_trade_value"),
                    "executed_turnover_ratio": rebalance_stats.get("executed_turnover_ratio"),
                    "skipped_turnover_ratio": rebalance_stats.get("skipped_turnover_ratio"),
                    "total_turnover_ratio": rebalance_stats.get("total_turnover_ratio"),
                    "skipped_weight_delta_trades": skip_reason_counts.get("weight_delta"),
                    "skipped_trade_value_ratio_trades": skip_reason_counts.get("trade_value_ratio"),
                    "skipped_min_shares_trades": skip_reason_counts.get("min_shares"),
                    "rationale": rationale,
                })
            for ticker, weight in sorted(final_stock_weights.items()):
                rows.append({
                    "date": date,
                    "regime": regime,
                    "entry_type": "target_ticker",
                    "sleeve": None,
                    "name": ticker,
                    "weight": weight,
                    "sleeve_return": None,
                    "weighted_contribution": None,
                    "support_count": None,
                    "support_ratio": None,
                    "average_sleeve_weight": None,
                    "executed_trades": rebalance_stats.get("executed_trades"),
                    "skipped_trades": rebalance_stats.get("skipped_trades"),
                    "executed_trade_value": rebalance_stats.get("executed_trade_value"),
                    "skipped_trade_value": rebalance_stats.get("skipped_trade_value"),
                    "executed_turnover_ratio": rebalance_stats.get("executed_turnover_ratio"),
                    "skipped_turnover_ratio": rebalance_stats.get("skipped_turnover_ratio"),
                    "total_turnover_ratio": rebalance_stats.get("total_turnover_ratio"),
                    "skipped_weight_delta_trades": skip_reason_counts.get("weight_delta"),
                    "skipped_trade_value_ratio_trades": skip_reason_counts.get("trade_value_ratio"),
                    "skipped_min_shares_trades": skip_reason_counts.get("min_shares"),
                    "rationale": rationale,
                })

        df = pd.DataFrame(rows, columns=["date", "regime", "entry_type", "sleeve", "name", "weight", "sleeve_return", "weighted_contribution", "support_count", "support_ratio", "average_sleeve_weight", "executed_trades", "skipped_trades", "executed_trade_value", "skipped_trade_value", "executed_turnover_ratio", "skipped_turnover_ratio", "total_turnover_ratio", "skipped_weight_delta_trades", "skipped_trade_value_ratio_trades", "skipped_min_shares_trades", "rationale"])
        csv_str = df.to_csv(index=False)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False)
            logger.info(f"FOF allocations CSV saved to {output_path}")

        return csv_str

    def _build_fof_equity_merge_frame(self, result) -> Optional[pd.DataFrame]:
        """Build a date-indexed DataFrame for merging FOF allocations into equity curve CSV."""
        allocations = (getattr(result, "config", {}) or {}).get("fof", {}).get("daily_allocations", [])
        if not allocations:
            return None

        rows = []
        for allocation in allocations:
            attribution_complete = bool(allocation.get("attribution_complete", True))
            row = {
                "date": allocation.get("date"),
                "fof_regime": allocation.get("regime"),
                "fof_rationale": allocation.get("rationale", ""),
            }
            for sleeve, weight in sorted((allocation.get("sleeve_weights") or {}).items()):
                row[f"fof_sleeve_{sleeve}"] = weight
            for sleeve, sleeve_return in sorted((allocation.get("sleeve_returns") or {}).items()):
                row[f"fof_sleeve_return_{sleeve}"] = sleeve_return if attribution_complete else None
            for sleeve, contribution in sorted((allocation.get("sleeve_contributions") or {}).items()):
                row[f"fof_sleeve_contribution_{sleeve}"] = contribution if attribution_complete else None
            row["fof_estimated_total_contribution"] = allocation.get("estimated_total_contribution") if attribution_complete else None
            consensus = allocation.get("sleeve_consensus", {}) or {}
            rebalance_stats = allocation.get("rebalance_stats", {}) or {}
            skip_reason_counts = rebalance_stats.get("skip_reason_counts", {}) or {}
            row["fof_avg_pairwise_overlap"] = consensus.get("average_pairwise_overlap")
            row["fof_consensus_distinct_tickers"] = consensus.get("distinct_ticker_count")
            row["fof_rebalance_executed_trades"] = rebalance_stats.get("executed_trades")
            row["fof_rebalance_skipped_trades"] = rebalance_stats.get("skipped_trades")
            row["fof_rebalance_executed_trade_value"] = rebalance_stats.get("executed_trade_value")
            row["fof_rebalance_skipped_trade_value"] = rebalance_stats.get("skipped_trade_value")
            row["fof_rebalance_executed_turnover_ratio"] = rebalance_stats.get("executed_turnover_ratio")
            row["fof_rebalance_skipped_turnover_ratio"] = rebalance_stats.get("skipped_turnover_ratio")
            row["fof_rebalance_total_turnover_ratio"] = rebalance_stats.get("total_turnover_ratio")
            row["fof_rebalance_skipped_weight_delta_trades"] = skip_reason_counts.get("weight_delta")
            row["fof_rebalance_skipped_trade_value_ratio_trades"] = skip_reason_counts.get("trade_value_ratio")
            row["fof_rebalance_skipped_min_shares_trades"] = skip_reason_counts.get("min_shares")
            for ticker, weight in sorted((allocation.get("final_stock_weights") or {}).items()):
                row[f"fof_target_{ticker}"] = weight
            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)
        if df.empty or "date" not in df.columns:
            return None
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def generate_equity_curve_csv(
        self,
        result,  # BacktestResult
        output_path: Optional[str] = None
    ) -> str:
        """
        Generate equity curve CSV file with daily portfolio values.

        Args:
            result: BacktestResult object
            output_path: Optional path to save CSV

        Returns:
            CSV content as string
        """
        equity_curve = result.tracker.get_equity_curve()

        if equity_curve.empty:
            logger.warning("No equity curve data to export")
            return ""

        if "date" in equity_curve.columns:
            equity_curve["date"] = pd.to_datetime(equity_curve["date"])

        benchmark_curve = getattr(result, "benchmark_curve", None)
        if isinstance(benchmark_curve, pd.Series) and not benchmark_curve.empty:
            bench_df = benchmark_curve.copy().rename("benchmark_value").reset_index()
            bench_df = bench_df.rename(columns={bench_df.columns[0]: "date"})
            bench_df["date"] = pd.to_datetime(bench_df["date"])
            equity_curve = equity_curve.merge(bench_df, on="date", how="left")
            if not equity_curve["benchmark_value"].dropna().empty:
                first_val = equity_curve["benchmark_value"].dropna().iloc[0]
                if first_val > 0:
                    equity_curve["benchmark_return"] = (
                        equity_curve["benchmark_value"] / first_val - 1
                    ) * 100

        fof_merge = self._build_fof_equity_merge_frame(result)
        if fof_merge is not None and not fof_merge.empty:
            equity_curve = equity_curve.merge(fof_merge, on="date", how="left")

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            equity_curve.to_csv(output_path, index=False)
            logger.info(f"Equity curve CSV saved to {output_path}")

        return equity_curve.to_csv(index=False)

    def generate_full_report(
        self,
        result,  # BacktestResult
        run_id: Optional[str] = None,
        token_stats_override: Optional[Dict] = None,
    ) -> Dict[str, str]:
        """
        Generate all report files.

        Args:
            result: BacktestResult object
            run_id: Optional run ID (will generate if not provided)

        Returns:
            Dict with paths to all generated files
        """
        run_id = run_id or result.run_id or self.generate_run_id()
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        paths = {
            "report_md": str(run_dir / "backtest_report.md"),
            "equity_curve": str(run_dir / "equity_curve.png"),
            "trades_csv": str(run_dir / "trades.csv"),
            "metrics_json": str(run_dir / "metrics.json"),
            "equity_curve_csv": str(run_dir / "equity_curve.csv"),
            "broker_audit_jsonl": str(run_dir / "broker_audit.jsonl"),
            "run_manifest_json": str(run_dir / "run_manifest.json"),
        }
        benchmark_diagnostics_path = str(run_dir / "benchmark_diagnostics.jsonl")

        fof_allocations = (getattr(result, "config", {}) or {}).get("fof", {}).get("daily_allocations", [])
        if fof_allocations:
            paths["fof_allocations_json"] = str(run_dir / "fof_allocations.json")
            paths["fof_allocations_csv"] = str(run_dir / "fof_allocations.csv")

        # Generate all reports
        self.generate_markdown(result, paths["report_md"], token_stats_override=token_stats_override)
        self.generate_equity_curve_chart(result, paths["equity_curve"])
        self.generate_trades_csv(result, paths["trades_csv"])
        self.generate_metrics_json(result, paths["metrics_json"])
        self.generate_equity_curve_csv(result, paths["equity_curve_csv"])
        self.generate_broker_audit_jsonl(result, paths["broker_audit_jsonl"])
        self.generate_run_manifest(
            result, paths["run_manifest_json"], token_stats_override=token_stats_override
        )
        benchmark_diagnostics = self.generate_benchmark_diagnostics_jsonl(benchmark_diagnostics_path)
        if benchmark_diagnostics:
            paths["benchmark_diagnostics_jsonl"] = benchmark_diagnostics_path
        if "fof_allocations_json" in paths:
            self.generate_fof_allocations_json(result, paths["fof_allocations_json"])
            self.generate_fof_allocations_csv(result, paths["fof_allocations_csv"])

        logger.info(f"Full report generated in {run_dir}")

        return paths
