"""Unit tests for the Fundamental Value backtest engine."""

from pathlib import Path
from types import SimpleNamespace

from backtest.fundamental_value_engine import FundamentalValueBacktestEngine


def _make_engine(tmp_path: Path) -> FundamentalValueBacktestEngine:
    return FundamentalValueBacktestEngine(
        tickers=["AAA", "BBB"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        db_path=str(tmp_path / "fundamental_value.db"),
        use_llm=False,
        personality="fundamental_value",
        config={
            "value_filter": {
                "max_ev_to_ebitda": 15.0,
                "min_fscore_lite": 3,
                "require_positive_roa": True,
                "require_positive_ocf": True,
                "min_current_ratio": 1.0,
                "require_positive_profit_margin": False,
            }
        },
    )


def test_evaluate_value_filter_passes_core_lite_checks(tmp_path: Path):
    engine = _make_engine(tmp_path)
    try:
        fundamentals = SimpleNamespace(
            ev_to_ebitda="10.5",
            return_on_assets_ttm="0.12",
            operating_cash_flow="1000000",
            current_ratio="1.8",
            profit_margin="0.15",
        )
        result = engine._evaluate_value_filter(fundamentals)
        assert result.passed is True
        assert result.lite_score == 3
        assert result.reasons == []
    finally:
        engine.close()


def test_evaluate_value_filter_fails_when_ev_to_ebitda_too_high(tmp_path: Path):
    engine = _make_engine(tmp_path)
    try:
        fundamentals = SimpleNamespace(
            ev_to_ebitda="21.0",
            return_on_assets_ttm="0.12",
            operating_cash_flow="1000000",
            current_ratio="1.8",
        )
        result = engine._evaluate_value_filter(fundamentals)
        assert result.passed is False
        assert "ev_to_ebitda" in result.reasons
    finally:
        engine.close()


def test_evaluate_value_filter_fails_safely_when_required_fields_missing(tmp_path: Path):
    engine = _make_engine(tmp_path)
    try:
        fundamentals = SimpleNamespace(
            ev_to_ebitda="N/A",
            return_on_assets_ttm="N/A",
            operating_cash_flow=None,
            current_ratio=None,
        )
        result = engine._evaluate_value_filter(fundamentals)
        assert result.passed is False
        assert result.lite_score == 0
        assert "roa" in result.reasons
        assert "operating_cash_flow" in result.reasons
        assert "current_ratio" in result.reasons
    finally:
        engine.close()


def test_value_behavior_metrics_aggregate_history(tmp_path: Path):
    engine = _make_engine(tmp_path)
    try:
        engine._value_filter_history = [
            {"date": "2024-01-02", "checked": 2, "passed": 1, "avg_normalized_score": 0.5},
            {"date": "2024-01-03", "checked": 2, "passed": 2, "avg_normalized_score": 0.75},
        ]
        metrics = engine._value_behavior_metrics()
        assert metrics["value_filter_pass_rate"] == 75.0
        assert metrics["value_consistency_score"] == 0.625
    finally:
        engine.close()
