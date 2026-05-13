import pytest
from backtest.report import ReportGenerator


def test_build_fof_section_renders_latest_allocations():
    generator = ReportGenerator()
    section = generator._build_fof_section(
        {
            "sleeves": ["conservative", "balanced", "aggressive", "passive"],
            "daily_allocations": [
                {
                    "date": "2024-01-01",
                    "regime": "neutral",
                    "sleeve_weights": {
                        "conservative": 0.40,
                        "balanced": 0.30,
                        "aggressive": 0.10,
                        "passive": 0.20,
                    },
                    "sleeve_target_weights": {
                        "conservative": {"AAA": 0.09, "BBB": 0.06},
                        "balanced": {"AAA": 0.10, "BBB": 0.07},
                    },
                    "sleeve_consensus": {
                        "average_pairwise_overlap": 0.58,
                        "distinct_ticker_count": 2,
                        "top_tickers": [
                            {"ticker": "AAA", "support_count": 2, "support_ratio": 1.0, "average_weight": 0.095, "aggregate_weight": 0.19},
                            {"ticker": "BBB", "support_count": 2, "support_ratio": 1.0, "average_weight": 0.065, "aggregate_weight": 0.13},
                        ],
                    },
                    "rebalance_stats": {
                        "executed_trades": 1,
                        "skipped_trades": 2,
                        "executed_trade_value": 800.0,
                        "skipped_trade_value": 300.0,
                        "executed_turnover_ratio": 0.008,
                        "skipped_turnover_ratio": 0.003,
                        "total_turnover_ratio": 0.011,
                        "skip_reason_counts": {"weight_delta": 0, "trade_value_ratio": 2, "min_shares": 0},
                    },
                    "final_stock_weights": {"AAA": 0.10, "BBB": 0.07},
                    "sleeve_returns": {"conservative": 0.00, "balanced": 0.01},
                    "sleeve_contributions": {"conservative": 0.0000, "balanced": 0.0030},
                    "rationale": "FOF meta allocation using 4 sleeves under neutral regime.",
                },
                {
                    "date": "2024-01-02",
                    "regime": "bear",
                    "sleeve_weights": {
                        "conservative": 0.35,
                        "balanced": 0.35,
                        "aggressive": 0.05,
                        "passive": 0.25,
                    },
                    "sleeve_target_weights": {
                        "conservative": {"AAA": 0.10, "BBB": 0.05},
                        "balanced": {"AAA": 0.12, "BBB": 0.08},
                    },
                    "sleeve_consensus": {
                        "average_pairwise_overlap": 0.62,
                        "distinct_ticker_count": 2,
                        "top_tickers": [
                            {"ticker": "AAA", "support_count": 2, "support_ratio": 1.0, "average_weight": 0.11, "aggregate_weight": 0.22},
                            {"ticker": "BBB", "support_count": 2, "support_ratio": 1.0, "average_weight": 0.065, "aggregate_weight": 0.13},
                        ],
                    },
                    "rebalance_stats": {
                        "executed_trades": 2,
                        "skipped_trades": 1,
                        "executed_trade_value": 1500.0,
                        "skipped_trade_value": 200.0,
                        "executed_turnover_ratio": 0.015,
                        "skipped_turnover_ratio": 0.002,
                        "total_turnover_ratio": 0.017,
                        "skip_reason_counts": {"weight_delta": 1, "trade_value_ratio": 0, "min_shares": 0},
                    },
                    "final_stock_weights": {"AAA": 0.12, "BBB": 0.08},
                    "sleeve_returns": {"conservative": -0.01, "balanced": 0.02},
                    "sleeve_contributions": {"conservative": -0.0035, "balanced": 0.0070},
                    "rationale": "FOF meta allocation using 4 sleeves under bear regime.",
                }
            ],
        }
    )

    assert "## FOF Diagnostics" in section
    assert "`bear`" in section
    assert "`conservative`" in section
    assert "`AAA`" in section
    assert "Latest Sleeve Attribution" in section
    assert "Latest Sleeve Consensus" in section
    assert "Cumulative Rebalance Summary" in section
    assert "Regime Turnover Summary" in section
    assert "Regime Skip Reason Summary" in section
    assert "Sleeve Stability Summary" in section
    assert "Latest Vs Avg Sleeve Deviation" in section
    assert "Sleeve Drift Alerts" in section
    assert "Sleeve Risk Contribution (MCR)" in section
    assert "Latest Rebalance Stats" in section
    assert "Executed Turnover Ratio" in section
    assert "Skip - Weight Delta" in section
    assert "Latest Sleeve Top Holdings" in section
    assert "**Executed Trades:** 3" in section
    assert "**Avg Total Turnover Ratio:** 1.40%" in section
    assert "**Peak Total Turnover Ratio:** 1.70%" in section
    assert "| `bear` | 1 | 2 | 1 | 1.70% | 1.70% |" in section
    assert "| `neutral` | 1 | 1 | 2 | 1.10% | 1.10% |" in section
    assert "| `bear` | 1 | `weight_delta` | 1 |" in section
    assert "| `neutral` | 2 | `trade_value_ratio` | 2 |" in section
    assert "| `balanced` | 32.50% | 30.00% | 35.00% | 5.00% |" in section
    assert "| `aggressive` | 7.50% | 5.00% | 10.00% | 5.00% |" in section
    assert "| `balanced` | 35.00% | 32.50% | +2.50% | 2.50% |" in section
    assert "**Threshold:** 5.00%" in section
    assert "| 2024-01-02 | `balanced` | 30.00% | 35.00% | +5.00% |" in section



def test_build_fof_section_uses_actual_final_positions_and_latest_completed_attribution():
    generator = ReportGenerator()

    class _Tracker:
        def get_summary(self):
            return {
                "final_value": 1000.0,
                "final_cash": 300.0,
                "final_positions": {
                    "REAL": {"shares": 5, "value": 500.0},
                    "ALT": {"shares": 2, "value": 200.0},
                },
            }

    section = generator._build_fof_section(
        {
            "sleeves": ["balanced", "passive"],
            "daily_allocations": [
                {
                    "date": "2024-01-01",
                    "regime": "neutral",
                    "sleeve_weights": {"balanced": 0.6, "passive": 0.4},
                    "sleeve_target_weights": {"balanced": {"TARGET": 0.12}, "passive": {"OLD": 0.08}},
                    "rebalance_stats": {"total_turnover_ratio": 0.01},
                    "final_stock_weights": {"TARGET": 0.12, "OLD": 0.08},
                    "sleeve_returns": {"balanced": 0.02, "passive": -0.01},
                    "sleeve_contributions": {"balanced": 0.012, "passive": -0.004},
                    "estimated_total_contribution": 0.008,
                    "attribution_complete": True,
                    "rationale": "previous day attribution",
                },
                {
                    "date": "2024-01-02",
                    "regime": "bear",
                    "sleeve_weights": {"balanced": 0.55, "passive": 0.45},
                    "sleeve_target_weights": {"balanced": {"TARGET": 0.10}, "passive": {"OLD": 0.06}},
                    "rebalance_stats": {"total_turnover_ratio": 0.02},
                    "final_stock_weights": {"TARGET": 0.10, "OLD": 0.06},
                    "sleeve_returns": {"balanced": 0.0, "passive": 0.0},
                    "sleeve_contributions": {"balanced": 0.0, "passive": 0.0},
                    "estimated_total_contribution": 0.0,
                    "attribution_complete": False,
                    "rationale": "latest day awaiting attribution",
                },
            ],
        },
        tracker=_Tracker(),
    )

    assert "| `REAL` | 50.00% |" in section
    assert "| `ALT` | 20.00% |" in section
    assert "| `TARGET` | 10.00% |" not in section
    assert "| `balanced` | +2.00% | +1.20% |" in section
    assert "| `passive` | -1.00% | -0.40% |" in section
    assert "**Attribution Snapshot Date:** 2024-01-01" in section
    assert "Attributed Weight" in section

def test_build_fof_section_supports_object_sleeves_from_real_config():
    generator = ReportGenerator()
    section = generator._build_fof_section(
        {
            "sleeves": [
                {"personality": "balanced", "weight": 0.6},
                {"personality": "passive", "weight": 0.4},
            ],
            "daily_allocations": [
                {
                    "date": "2024-01-02",
                    "regime": "neutral",
                    "sleeve_weights": {"balanced": 0.6, "passive": 0.4},
                    "sleeve_target_weights": {"balanced": {"AAA": 0.1}, "passive": {"BBB": 0.08}},
                    "sleeve_returns": {"balanced": 0.01, "passive": 0.0},
                    "sleeve_contributions": {"balanced": 0.006, "passive": 0.0},
                    "attribution_complete": True,
                    "rebalance_stats": {"total_turnover_ratio": 0.01},
                    "final_stock_weights": {"AAA": 0.1, "BBB": 0.08},
                    "rationale": "object sleeve config smoke test",
                }
            ],
        }
    )

    assert "## FOF Diagnostics" in section
    assert "`balanced`" in section
    assert "`passive`" in section


def test_compute_mcr_summary_returns_expected_numeric_contributions():
    generator = ReportGenerator()
    summary = generator._compute_mcr_summary(
        [
            {
                "sleeve_weights": {"balanced": 0.6, "passive": 0.4},
                "sleeve_returns": {"balanced": 0.02, "passive": 0.01},
                "attribution_complete": True,
            },
            {
                "sleeve_weights": {"balanced": 0.5, "passive": 0.5},
                "sleeve_returns": {"balanced": -0.01, "passive": 0.03},
                "attribution_complete": True,
            },
            {
                "sleeve_weights": {"balanced": 0.55, "passive": 0.45},
                "sleeve_returns": {"balanced": 0.01, "passive": 0.02},
                "attribution_complete": True,
            },
        ]
    )

    assert summary["portfolio_volatility"] == pytest.approx(0.00407226, abs=1e-6)
    rows = {item["sleeve"]: item for item in summary["rows"]}
    assert rows["balanced"]["latest_weight"] == pytest.approx(0.55, abs=1e-6)
    assert rows["balanced"]["mcr"] == pytest.approx(0.014938, abs=1e-6)
    assert rows["balanced"]["component_contribution"] == pytest.approx(0.008216, abs=1e-6)
    assert rows["passive"]["latest_weight"] == pytest.approx(0.45, abs=1e-6)
    assert rows["passive"]["mcr"] == pytest.approx(-0.009209, abs=1e-6)
    assert rows["passive"]["component_contribution"] == pytest.approx(-0.004144, abs=1e-6)


def test_generate_fof_exports_blank_pending_attribution_values(tmp_path):
    from io import StringIO
    from types import SimpleNamespace
    import pandas as pd

    generator = ReportGenerator(output_dir=str(tmp_path))
    result = SimpleNamespace(
        run_id="fof_pending",
        tracker=SimpleNamespace(
            get_equity_curve=lambda: pd.DataFrame([
                {"date": "2024-01-02", "total_value": 100000.0, "daily_return": 0.0, "cashflow": 50000.0},
            ])
        ),
        benchmark_curve=None,
        config={
            "personality": "fof",
            "fof": {
                "daily_allocations": [
                    {
                        "date": "2024-01-02",
                        "regime": "neutral",
                        "sleeve_weights": {"balanced": 0.6},
                        "sleeve_returns": {"balanced": 0.0},
                        "sleeve_contributions": {"balanced": 0.0},
                        "estimated_total_contribution": 0.0,
                        "attribution_complete": False,
                        "rebalance_stats": {"total_turnover_ratio": 0.01},
                    }
                ]
            },
        },
    )

    csv_payload = generator.generate_fof_allocations_csv(result)
    alloc_df = pd.read_csv(StringIO(csv_payload))
    sleeve_row = alloc_df[alloc_df["entry_type"] == "sleeve"].iloc[0]
    assert pd.isna(sleeve_row["sleeve_return"])
    assert pd.isna(sleeve_row["weighted_contribution"])

    equity_csv = generator.generate_equity_curve_csv(result)
    equity_df = pd.read_csv(StringIO(equity_csv))
    assert pd.isna(equity_df.loc[0, "fof_sleeve_return_balanced"])
    assert pd.isna(equity_df.loc[0, "fof_sleeve_contribution_balanced"])
    assert pd.isna(equity_df.loc[0, "fof_estimated_total_contribution"])


def test_generate_fof_allocation_exports(tmp_path):
    from types import SimpleNamespace

    generator = ReportGenerator(output_dir=str(tmp_path))
    result = SimpleNamespace(
        run_id="fof_run",
        config={
            "personality": "fof",
            "fof": {
                "sleeves": ["conservative", "balanced"],
                "daily_allocations": [
                    {
                        "date": "2024-01-02",
                        "regime": "neutral",
                        "sleeve_weights": {"conservative": 0.4, "balanced": 0.6},
                        "sleeve_target_weights": {
                            "conservative": {"AAA": 0.10, "BBB": 0.05},
                            "balanced": {"AAA": 0.12, "BBB": 0.08},
                        },
                        "sleeve_consensus": {
                            "average_pairwise_overlap": 0.62,
                            "distinct_ticker_count": 2,
                            "top_tickers": [
                                {"ticker": "AAA", "support_count": 2, "support_ratio": 1.0, "average_weight": 0.11, "aggregate_weight": 0.22}
                            ],
                        },
                        "rebalance_stats": {
                            "executed_trades": 2,
                            "skipped_trades": 1,
                            "executed_trade_value": 1500.0,
                            "skipped_trade_value": 200.0,
                        },
                        "final_stock_weights": {"AAA": 0.12, "BBB": 0.08},
                        "sleeve_returns": {"conservative": -0.01, "balanced": 0.02},
                        "sleeve_contributions": {"conservative": -0.004, "balanced": 0.012},
                        "estimated_total_contribution": 0.008,
                        "rationale": "test rationale",
                    }
                ],
            },
        },
    )

    json_path = tmp_path / "fof_allocations.json"
    csv_path = tmp_path / "fof_allocations.csv"
    json_payload = generator.generate_fof_allocations_json(result, str(json_path))
    csv_payload = generator.generate_fof_allocations_csv(result, str(csv_path))

    assert '"daily_allocations"' in json_payload
    assert "entry_type" in csv_payload
    assert "target_ticker" in csv_payload
    assert "weighted_contribution" in csv_payload
    assert "sleeve_ticker" in csv_payload
    assert "consensus_ticker" in csv_payload
    assert "executed_trades" in csv_payload
    assert "executed_trade_value" in csv_payload
    assert "skipped_weight_delta_trades" in csv_payload
    assert "executed_turnover_ratio" in csv_payload
    assert "conservative,AAA" in csv_payload or ",conservative,AAA," in csv_payload
    assert ",AAA,0.22," in csv_payload or "consensus_ticker" in csv_payload
    assert json_path.exists()
    assert csv_path.exists()


def test_generate_equity_curve_csv_merges_fof_allocations(tmp_path):
    from types import SimpleNamespace
    import pandas as pd

    class _Tracker:
        def get_equity_curve(self):
            return pd.DataFrame(
                [
                    {"date": "2024-01-02", "total_value": 100000.0, "daily_return": 0.0, "cashflow": 50000.0},
                    {"date": "2024-01-03", "total_value": 101000.0, "daily_return": 1.0, "cashflow": 48000.0},
                ]
            )

    generator = ReportGenerator(output_dir=str(tmp_path))
    result = SimpleNamespace(
        tracker=_Tracker(),
        benchmark_curve=None,
        config={
            "personality": "fof",
            "fof": {
                "daily_allocations": [
                    {
                        "date": "2024-01-02",
                        "regime": "neutral",
                        "sleeve_weights": {"balanced": 0.6, "passive": 0.4},
                        "sleeve_target_weights": {
                            "balanced": {"AAA": 0.12, "BBB": 0.08},
                            "passive": {"AAA": 0.10, "BBB": 0.10},
                        },
                        "sleeve_consensus": {
                            "average_pairwise_overlap": 0.75,
                            "distinct_ticker_count": 2,
                            "top_tickers": [
                                {"ticker": "AAA", "support_count": 2, "support_ratio": 1.0, "average_weight": 0.11, "aggregate_weight": 0.22}
                            ],
                        },
                        "rebalance_stats": {
                            "executed_trades": 1,
                            "skipped_trades": 2,
                            "executed_trade_value": 800.0,
                            "skipped_trade_value": 300.0,
                            "executed_turnover_ratio": 0.008,
                            "skipped_turnover_ratio": 0.003,
                            "total_turnover_ratio": 0.011,
                        },
                        "final_stock_weights": {"AAA": 0.12, "BBB": 0.08},
                        "sleeve_returns": {"conservative": -0.01, "balanced": 0.02},
                        "sleeve_contributions": {"conservative": -0.004, "balanced": 0.012},
                        "estimated_total_contribution": 0.008,
                        "rationale": "test rationale",
                    }
                ]
            },
        },
    )

    csv_payload = generator.generate_equity_curve_csv(result, str(tmp_path / "equity_curve.csv"))

    assert "fof_regime" in csv_payload
    assert "fof_sleeve_balanced" in csv_payload
    assert "fof_target_AAA" in csv_payload
    assert "fof_sleeve_contribution_balanced" in csv_payload
    assert "fof_avg_pairwise_overlap" in csv_payload
    assert "fof_rebalance_skipped_trades" in csv_payload
    assert "fof_rebalance_skipped_weight_delta_trades" in csv_payload
    assert "fof_rebalance_total_turnover_ratio" in csv_payload


def test_generate_markdown_places_fof_overview_near_top(tmp_path):
    from types import SimpleNamespace

    class _Tracker:
        def get_trades(self):
            return []

        def get_buy_count(self):
            return 0

        def get_sell_count(self):
            return 0

        def get_position_summary(self):
            return {}

        def get_summary(self):
            return {
                "final_value": 100000.0,
                "final_cash": 30000.0,
                "final_positions": {
                    "REAL": {"shares": 7, "value": 70000.0},
                },
            }

    generator = ReportGenerator(output_dir=str(tmp_path))
    result = SimpleNamespace(
        run_id="fof_overview_run",
        start_date="2024-01-01",
        end_date="2024-01-02",
        market="cn",
        tickers=["AAA", "BBB"],
        initial_cash=100000.0,
        tracker=_Tracker(),
        metrics={
            "initial_cash": 100000.0,
            "final_value": 101700.0,
            "total_return": 1.7,
            "annualized_return": 12.0,
            "trading_days": 2,
            "sharpe_ratio": 1.2,
            "sortino_ratio": 1.4,
            "max_drawdown": -1.0,
            "max_drawdown_duration": 1,
            "volatility": 8.0,
            "win_rate": 50.0,
        },
        config={
            "personality": "fof",
            "fof": {
                "sleeves": ["conservative", "balanced", "aggressive", "passive"],
                "daily_allocations": [
                    {
                        "date": "2024-01-01",
                        "regime": "neutral",
                        "sleeve_weights": {"conservative": 0.40, "balanced": 0.30, "aggressive": 0.10, "passive": 0.20},
                        "rebalance_stats": {
                            "executed_trades": 1,
                            "skipped_trades": 2,
                            "total_turnover_ratio": 0.011,
                            "skip_reason_counts": {"weight_delta": 0, "trade_value_ratio": 2, "min_shares": 0},
                        },
                        "final_stock_weights": {"AAA": 0.10, "BBB": 0.07},
                        "rationale": "neutral setup",
                    },
                    {
                        "date": "2024-01-02",
                        "regime": "bear",
                        "sleeve_weights": {"conservative": 0.35, "balanced": 0.35, "aggressive": 0.05, "passive": 0.25},
                        "rebalance_stats": {
                            "executed_trades": 2,
                            "skipped_trades": 1,
                            "total_turnover_ratio": 0.017,
                            "skip_reason_counts": {"weight_delta": 1, "trade_value_ratio": 0, "min_shares": 0},
                        },
                        "final_stock_weights": {"AAA": 0.12, "BBB": 0.08},
                        "rationale": "bear setup",
                    },
                ],
            },
        },
    )

    report = generator.generate_markdown(result)

    assert "## FOF Overview" in report
    assert report.index("## FOF Overview") < report.index("## Performance Metrics")
    assert report.index("## FOF Overview") < report.index("## FOF Diagnostics")
    assert "| **Current State** | regime `bear`, turnover 1.70% |" in report
    assert "| **Turnover Profile** | avg 1.40% / peak 1.70% |" in report
    assert "| **Rebalance Activity** | executed 3, skipped 3 |" in report
    assert "| **Latest Top Positions** | `REAL` 70.00% |" in report
    assert "| **Sleeve Signal** | deviation `balanced` +2.50%; alerts 4 above 5.00% |" in report


def test_generate_full_report_fof_smoke(tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    import pandas as pd

    class _Tracker:
        def get_trades(self):
            return []

        def get_buy_count(self):
            return 0

        def get_sell_count(self):
            return 0

        def get_position_summary(self):
            return {"AAA": {"shares": 10, "value": 1200.0}}

        def get_summary(self):
            return {"final_cash": 98000.0}

        def get_trades_df(self):
            return pd.DataFrame(columns=["date", "ticker", "action", "shares", "price", "value"])

        def get_equity_curve(self):
            return pd.DataFrame(
                [
                    {"date": "2024-01-01", "total_value": 100000.0, "daily_return": 0.0, "cashflow": 100000.0},
                    {"date": "2024-01-02", "total_value": 101700.0, "daily_return": 1.7, "cashflow": 98000.0},
                ]
            )

    generator = ReportGenerator(output_dir=str(tmp_path))
    result = SimpleNamespace(
        run_id="fof_smoke_run",
        start_date="2024-01-01",
        end_date="2024-01-02",
        market="us",
        tickers=["AAA", "BBB"],
        initial_cash=100000.0,
        tracker=_Tracker(),
        benchmark_curve=None,
        metrics={
            "initial_cash": 100000.0,
            "final_value": 101700.0,
            "total_return": 1.7,
            "annualized_return": 12.0,
            "trading_days": 2,
            "sharpe_ratio": 1.2,
            "sortino_ratio": 1.4,
            "max_drawdown": -1.0,
            "max_drawdown_duration": 1,
            "volatility": 8.0,
            "win_rate": 50.0,
        },
        config={
            "personality": "fof",
            "fof": {
                "sleeves": ["conservative", "balanced"],
                "daily_allocations": [
                    {
                        "date": "2024-01-01",
                        "regime": "neutral",
                        "sleeve_weights": {"conservative": 0.40, "balanced": 0.60},
                        "sleeve_target_weights": {
                            "conservative": {"AAA": 0.10, "BBB": 0.05},
                            "balanced": {"AAA": 0.12, "BBB": 0.08},
                        },
                        "sleeve_consensus": {
                            "average_pairwise_overlap": 0.62,
                            "distinct_ticker_count": 2,
                            "top_tickers": [
                                {"ticker": "AAA", "support_count": 2, "support_ratio": 1.0, "average_weight": 0.11, "aggregate_weight": 0.22}
                            ],
                        },
                        "rebalance_stats": {
                            "executed_trades": 1,
                            "skipped_trades": 1,
                            "executed_trade_value": 1000.0,
                            "skipped_trade_value": 200.0,
                            "executed_turnover_ratio": 0.01,
                            "skipped_turnover_ratio": 0.002,
                            "total_turnover_ratio": 0.012,
                            "skip_reason_counts": {"weight_delta": 1, "trade_value_ratio": 0, "min_shares": 0},
                        },
                        "final_stock_weights": {"AAA": 0.12, "BBB": 0.08},
                        "sleeve_returns": {"conservative": -0.01, "balanced": 0.02},
                        "sleeve_contributions": {"conservative": -0.004, "balanced": 0.012},
                        "estimated_total_contribution": 0.008,
                        "rationale": "smoke rationale",
                    },
                    {
                        "date": "2024-01-02",
                        "regime": "bear",
                        "sleeve_weights": {"conservative": 0.45, "balanced": 0.55},
                        "sleeve_target_weights": {
                            "conservative": {"AAA": 0.11, "BBB": 0.04},
                            "balanced": {"AAA": 0.13, "BBB": 0.07},
                        },
                        "sleeve_consensus": {
                            "average_pairwise_overlap": 0.70,
                            "distinct_ticker_count": 2,
                            "top_tickers": [
                                {"ticker": "AAA", "support_count": 2, "support_ratio": 1.0, "average_weight": 0.12, "aggregate_weight": 0.24}
                            ],
                        },
                        "rebalance_stats": {
                            "executed_trades": 2,
                            "skipped_trades": 0,
                            "executed_trade_value": 1500.0,
                            "skipped_trade_value": 0.0,
                            "executed_turnover_ratio": 0.015,
                            "skipped_turnover_ratio": 0.0,
                            "total_turnover_ratio": 0.015,
                            "skip_reason_counts": {"weight_delta": 0, "trade_value_ratio": 0, "min_shares": 0},
                        },
                        "final_stock_weights": {"AAA": 0.13, "BBB": 0.07},
                        "sleeve_returns": {"conservative": 0.01, "balanced": 0.02},
                        "sleeve_contributions": {"conservative": 0.0045, "balanced": 0.0110},
                        "estimated_total_contribution": 0.0155,
                        "rationale": "smoke rationale bear",
                    },
                ],
            },
        },
    )

    paths = generator.generate_full_report(result)

    assert Path(paths["report_md"]).exists()
    assert Path(paths["trades_csv"]).exists()
    assert Path(paths["metrics_json"]).exists()
    assert Path(paths["equity_curve_csv"]).exists()
    assert Path(paths["fof_allocations_json"]).exists()
    assert Path(paths["fof_allocations_csv"]).exists()

    report_payload = Path(paths["report_md"]).read_text(encoding="utf-8")
    assert "## FOF Overview" in report_payload
    assert "## FOF Diagnostics" in report_payload
    assert "smoke rationale bear" in report_payload

    equity_csv = Path(paths["equity_curve_csv"]).read_text(encoding="utf-8")
    assert "fof_rebalance_total_turnover_ratio" in equity_csv

def test_compute_mcr_summary_ignores_incomplete_attribution_rows():
    generator = ReportGenerator()
    summary = generator._compute_mcr_summary(
        [
            {
                "sleeve_weights": {"balanced": 0.6, "passive": 0.4},
                "sleeve_returns": {"balanced": 0.02, "passive": 0.01},
                "attribution_complete": True,
            },
            {
                "sleeve_weights": {"balanced": 0.5, "passive": 0.5},
                "sleeve_returns": {"balanced": -0.01, "passive": 0.03},
                "attribution_complete": True,
            },
            {
                "sleeve_weights": {"balanced": 0.55, "passive": 0.45},
                "sleeve_returns": {"balanced": 0.0, "passive": 0.0},
                "attribution_complete": False,
            },
        ]
    )

    rows = {item["sleeve"]: item for item in summary["rows"]}
    assert rows["balanced"]["latest_weight"] == pytest.approx(0.5, abs=1e-6)
    assert rows["passive"]["latest_weight"] == pytest.approx(0.5, abs=1e-6)



def test_compute_mcr_summary_ignores_sparse_missing_histories():
    generator = ReportGenerator()
    sparse_summary = generator._compute_mcr_summary(
        [
            {
                "sleeve_weights": {"balanced": 0.6, "passive": 0.4},
                "sleeve_returns": {"balanced": 0.02, "passive": 0.01},
                "attribution_complete": True,
            },
            {
                "sleeve_weights": {"balanced": 0.5},
                "sleeve_returns": {"balanced": -0.01},
                "attribution_complete": True,
            },
            {
                "sleeve_weights": {"balanced": 0.55, "passive": 0.45},
                "sleeve_returns": {"balanced": 0.01, "passive": 0.02},
                "attribution_complete": True,
            },
        ]
    )
    dense_summary = generator._compute_mcr_summary(
        [
            {
                "sleeve_weights": {"balanced": 0.6, "passive": 0.4},
                "sleeve_returns": {"balanced": 0.02, "passive": 0.01},
                "attribution_complete": True,
            },
            {
                "sleeve_weights": {"balanced": 0.55, "passive": 0.45},
                "sleeve_returns": {"balanced": 0.01, "passive": 0.02},
                "attribution_complete": True,
            },
        ]
    )

    assert sparse_summary["portfolio_volatility"] == pytest.approx(dense_summary["portfolio_volatility"], abs=1e-9)
    sparse_rows = {item["sleeve"]: item for item in sparse_summary["rows"]}
    dense_rows = {item["sleeve"]: item for item in dense_summary["rows"]}
    assert sparse_rows.keys() == dense_rows.keys()
    for sleeve in sparse_rows:
        assert sparse_rows[sleeve]["mcr"] == pytest.approx(dense_rows[sleeve]["mcr"], abs=1e-9)
        assert sparse_rows[sleeve]["component_contribution"] == pytest.approx(
            dense_rows[sleeve]["component_contribution"], abs=1e-9
        )

def test_generate_fof_allocations_json_is_strict_json(tmp_path):
    from io import StringIO
    from types import SimpleNamespace
    import json

    generator = ReportGenerator(output_dir=str(tmp_path))
    result = SimpleNamespace(
        run_id="fof-json",
        config={
            "personality": "fof",
            "fof": {
                "sleeves": ["balanced"],
                "daily_allocations": [
                    {
                        "date": "2024-01-02",
                        "regime": "neutral",
                        "sleeve_weights": {"balanced": float("inf")},
                    }
                ],
            },
        },
    )

    payload = generator.generate_fof_allocations_json(result)
    parsed = json.loads(payload)
    assert parsed["daily_allocations"][0]["sleeve_weights"]["balanced"] is None

