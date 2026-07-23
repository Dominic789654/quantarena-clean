"""Characterization tests for `BacktestWorkflowAdapter.run_single_day` —
its only untested public method prior to this change
(docs/refactor_program_plan.md Phase 3, step 19: add-run-single-day-
characterization-test). Covers three paths:

(a) happy path — `graph.workflow.AgentWorkflow` stubbed so each ticker
    gets a real decision; asserts `BacktestDecision` fields and the
    resulting portfolio update.
(b) the outer `ImportError` fallback — every priced ticker gets a HOLD
    decision, portfolio untouched.
(c) the per-ticker exception fallback — one ticker's fake workflow
    raises; only that ticker HOLDs, the other tickers still get their
    real decisions and portfolio updates.

`run_single_day` does `from graph.workflow import AgentWorkflow` (and
three other imports) *inside* its own body on every call, so the
import always re-reads the current `AgentWorkflow` attribute off the
already-imported `graph.workflow` module object cached in
`sys.modules`. Test (a)/(c) stub that import site by monkeypatching the
`AgentWorkflow` attribute directly on the `graph.workflow` module.
Test (b) instead forces the import itself to fail via
`monkeypatch.setitem(sys.modules, "graph.workflow", None)` — the
standard technique for forcing `ImportError` on an already-cached
module name; Python's import machinery raises `ImportError` immediately
when a module name maps to `None` in `sys.modules`.

This change is test-only; no production code in `backtest/` changed.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from backtest.workflow_adapter import BacktestWorkflowAdapter


def _make_fake_agent_workflow(decisions_by_ticker: Dict[str, Any], fail_tickers: Optional[set] = None):
    """Build a fake replacement for `graph.workflow.AgentWorkflow`.

    `decisions_by_ticker[ticker]` is returned as the `"decision"` entry
    of `invoke`'s final state for that ticker (a plain
    `types.SimpleNamespace` with `action`/`shares`/`price`/
    `justification` attributes is enough — `run_single_day` only ever
    does attribute access on the decision, never an isinstance check).
    `load_analysts` raises for any ticker in `fail_tickers`, landing in
    `run_single_day`'s per-ticker `except Exception` fallback.
    `update_portfolio_ticker` mirrors the real
    `graph.workflow.AgentWorkflow.update_portfolio_ticker` /
    `backtest.workflow.decision_apply._update_portfolio_ticker` logic
    (BUY adds shares and spends cash, SELL removes shares and receives
    cash, position value is repriced, cashflow rounded).
    """
    fail_tickers = fail_tickers or set()

    class FakeAgentWorkflow:
        def __init__(self, config, config_id, market):
            self.config = config
            self.config_id = config_id
            self.market = market
            self.init_portfolio = None

        def load_analysts(self, ticker):
            if ticker in fail_tickers:
                raise RuntimeError(f"stubbed analyst failure for {ticker}")

        def build(self):
            return self

        def invoke(self, state):
            ticker = state["ticker"]
            return {"decision": decisions_by_ticker[ticker], "analyst_signals": []}

        def update_portfolio_ticker(self, portfolio, ticker, decision):
            from graph.schema import Position

            action = str(getattr(decision, "action", "HOLD")).strip().upper()
            shares = int(getattr(decision, "shares", 0) or 0)
            price = float(getattr(decision, "price", 0.0) or 0.0)

            if ticker not in portfolio.positions:
                portfolio.positions[ticker] = Position(shares=0, value=0)

            if action == "BUY":
                portfolio.positions[ticker].shares += shares
                portfolio.cashflow -= price * shares
            elif action == "SELL":
                portfolio.positions[ticker].shares -= shares
                portfolio.cashflow += price * shares

            portfolio.positions[ticker].value = round(price * portfolio.positions[ticker].shares, 2)
            portfolio.cashflow = round(portfolio.cashflow, 2)
            return portfolio

    return FakeAgentWorkflow


def _make_adapter(tmp_path: Path, tickers) -> BacktestWorkflowAdapter:
    return BacktestWorkflowAdapter(
        tickers=tickers,
        initial_cash=100000.0,
        market="cn",
        analysts=["fundamental"],
        personality="balanced",
        db_path=str(tmp_path / "adapter.db"),
        llm_provider="test_provider",
        llm_model="test_model",
    )


def test_run_single_day_happy_path_builds_decisions_and_updates_portfolio(tmp_path, monkeypatch):
    """(a) Stub graph.workflow.AgentWorkflow so each ticker returns a
    decision; assert BacktestDecision fields and portfolio updates."""
    import graph.workflow as graph_workflow_module

    decisions_by_ticker = {
        "AAA": SimpleNamespace(action="BUY", shares=10, price=100.0, justification="buy AAA"),
        "BBB": SimpleNamespace(action="HOLD", shares=0, price=50.0, justification="hold BBB"),
    }
    monkeypatch.setattr(
        graph_workflow_module,
        "AgentWorkflow",
        _make_fake_agent_workflow(decisions_by_ticker),
    )

    adapter = _make_adapter(tmp_path, ["AAA", "BBB"])
    try:
        decisions = adapter.run_single_day("2026-01-02", {"AAA": 100.0, "BBB": 50.0})
    finally:
        adapter.close()

    assert set(decisions.keys()) == {"AAA", "BBB"}

    aaa = decisions["AAA"]
    assert aaa.ticker == "AAA"
    assert aaa.action == "BUY"
    assert aaa.shares == 10
    assert aaa.price == 100.0
    assert aaa.justification == "buy AAA"
    assert aaa.analyst_signals == {}

    bbb = decisions["BBB"]
    assert bbb.action == "HOLD"
    assert bbb.shares == 0
    assert bbb.justification == "hold BBB"

    # AAA bought 10 @ 100 -> cash down by 1000, AAA position now 10 shares.
    portfolio = adapter.get_current_portfolio()
    assert portfolio["cashflow"] == pytest.approx(100000.0 - 1000.0)
    assert portfolio["positions"]["AAA"]["shares"] == 10
    assert portfolio["positions"]["AAA"]["value"] == pytest.approx(1000.0)
    assert portfolio["positions"]["BBB"]["shares"] == 0


def test_run_single_day_import_error_returns_hold_for_all_tickers(tmp_path, monkeypatch):
    """(b) Force `from graph.workflow import AgentWorkflow` to raise
    ImportError; assert every priced ticker gets a HOLD decision and the
    portfolio is left untouched."""
    monkeypatch.setitem(sys.modules, "graph.workflow", None)

    adapter = _make_adapter(tmp_path, ["AAA", "BBB"])
    try:
        decisions = adapter.run_single_day("2026-01-02", {"AAA": 100.0, "BBB": 50.0})
    finally:
        adapter.close()

    assert set(decisions.keys()) == {"AAA", "BBB"}
    for ticker, price in (("AAA", 100.0), ("BBB", 50.0)):
        decision = decisions[ticker]
        assert decision.action == "HOLD"
        assert decision.shares == 0
        assert decision.price == price
        assert decision.justification.startswith("Import error:")
        assert decision.analyst_signals == {}

    # The import failed before any decision-application code ran.
    portfolio = adapter.get_current_portfolio()
    assert portfolio["cashflow"] == 100000.0
    assert portfolio["positions"]["AAA"]["shares"] == 0
    assert portfolio["positions"]["BBB"]["shares"] == 0


def test_run_single_day_per_ticker_exception_holds_only_that_ticker(tmp_path, monkeypatch):
    """(c) One ticker's workflow raises inside the per-ticker try/except;
    assert that ticker HOLDs while the other tickers still get their
    real decisions and portfolio updates."""
    import graph.workflow as graph_workflow_module

    decisions_by_ticker = {
        "AAA": SimpleNamespace(action="BUY", shares=5, price=100.0, justification="buy AAA"),
        "CCC": SimpleNamespace(action="BUY", shares=2, price=20.0, justification="buy CCC"),
    }
    monkeypatch.setattr(
        graph_workflow_module,
        "AgentWorkflow",
        _make_fake_agent_workflow(decisions_by_ticker, fail_tickers={"BBB"}),
    )

    adapter = _make_adapter(tmp_path, ["AAA", "BBB", "CCC"])
    try:
        decisions = adapter.run_single_day(
            "2026-01-02",
            {"AAA": 100.0, "BBB": 50.0, "CCC": 20.0},
        )
    finally:
        adapter.close()

    assert set(decisions.keys()) == {"AAA", "BBB", "CCC"}

    bbb = decisions["BBB"]
    assert bbb.action == "HOLD"
    assert bbb.shares == 0
    assert bbb.price == 50.0
    assert bbb.justification.startswith("Error:")
    assert "stubbed analyst failure for BBB" in bbb.justification
    assert bbb.analyst_signals == {}

    aaa = decisions["AAA"]
    assert aaa.action == "BUY"
    assert aaa.shares == 5

    ccc = decisions["CCC"]
    assert ccc.action == "BUY"
    assert ccc.shares == 2

    portfolio = adapter.get_current_portfolio()
    # AAA bought 5 @ 100 (-500), CCC bought 2 @ 20 (-40); BBB untouched.
    assert portfolio["cashflow"] == pytest.approx(100000.0 - 500.0 - 40.0)
    assert portfolio["positions"]["AAA"]["shares"] == 5
    assert portfolio["positions"]["CCC"]["shares"] == 2
    assert portfolio["positions"]["BBB"]["shares"] == 0
