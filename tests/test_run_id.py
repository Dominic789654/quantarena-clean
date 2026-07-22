"""Tests for generated run identifiers."""

from shared.utils.run_id import generate_run_id


def test_generate_run_id_is_unique_for_rapid_calls():
    run_ids = [generate_run_id() for _ in range(100)]

    assert len(run_ids) == len(set(run_ids))


def test_generate_run_id_includes_prefix_without_losing_entropy():
    run_id = generate_run_id("mp_balanced")

    assert run_id.startswith("mp_balanced_")
    assert len(run_id.split("_")) >= 5


def test_backtest_engine_default_run_ids_are_unique_for_rapid_finalize_calls(monkeypatch):
    from backtest.engine import BacktestEngine
    from backtest.portfolio_tracker import PortfolioTracker

    class _Reporter:
        def generate_full_report(self, *args, **kwargs):
            return {}

    def make_engine():
        engine = BacktestEngine.__new__(BacktestEngine)
        engine.start_date = "2026-01-02"
        engine.end_date = "2026-01-02"
        engine.tickers = ["AAPL"]
        engine.market = "us"
        engine.initial_cash = 100000.0
        engine.config = {"benchmark": {"mode": "none"}}
        engine.benchmark_mode = "none"
        engine.use_llm = False
        engine.tracker = PortfolioTracker(initial_cash=100000.0)
        engine.tracker.record_snapshot("2026-01-02", 100000.0, positions={}, prices={})
        engine.reporter = _Reporter()
        engine.broker_audit_events = []
        return engine

    monkeypatch.setattr(BacktestEngine, "_get_final_prices", lambda self, last_date: {"AAPL": 100.0})

    run_ids = [
        make_engine().finalize_run(
            trading_days=["2026-01-02"],
            run_id=None,
            generate_report=False,
        ).run_id
        for _ in range(25)
    ]

    assert len(run_ids) == len(set(run_ids))
