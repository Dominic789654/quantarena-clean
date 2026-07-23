"""Reusable characterization-test fixtures for `deepear.src.agents.report_agent.ReportAgent`.

This module exists because, before the `build-report-agent-characterization-harness`
change, zero tests constructed a real `ReportAgent` except
`tests/test_report_agent_citations.py` (the seed for the pattern used here). It is
imported directly (not via a pytest plugin) so that later Phase 4 extraction changes
(`extract-report-agent-retry-helper`, `extract-report-agent-citation-manager`, etc.)
can `from tests.report_agent_harness import ...` and reuse the same fakes without
re-deriving the `agno.agent.Agent` / `DatabaseManager` / `ForecastAgent` surfaces.

Design (see openspec/changes/build-report-agent-characterization-harness/design.md
for the full rationale):

- `FakeModel` is a minimal stand-in for `agno.models.base.Model`; `ReportAgent`
  never calls anything on it directly, but `hasattr(self.tool_model,
  'response_format')` gates whether the Planner agent gets an `output_schema`, so
  `FakeModel` supports toggling that attribute on.
- `FakeAgent` replaces `agno.agent.Agent`. It never runs a real tool loop (the
  `tools=[self.rag.search]` kwarg is stored but never invoked) -- responses are
  scripted, either via a direct `run_fn` callable (for direct
  `_run_agent_with_retry` tests) or via a shared `ScriptedAgentRouter` (for
  `ReportAgent`-level tests, where the four internal agents -- planner, writer,
  editor, section_editor -- all dispatch off the same router, exactly like the
  seed test in test_report_agent_citations.py dispatches off prompt substrings).
- `FakeDatabaseManager` implements exactly the `DatabaseManager` surface
  `ReportAgent` touches, directly (`lookup_reference_by_url`, `execute_query`) and
  via the `StockTools` collaborator it constructs internally
  (`get_stock_prices`, `save_stock_prices`, `search_stock`).
- `make_report_agent` builds a *real* `ReportAgent`, monkeypatching only the two
  construction-time seams needed to keep it hermetic: the `Agent` class (so no
  network/LLM calls happen) and the `ForecastAgent` class (so the real,
  optionally Kronos-backed forecast pipeline is never imported/constructed) --
  the real `_get_forecast_agent` lazy-caching method is left untouched, so tests
  can characterize its actual "construct at most once" behavior.

Since `finalize-report-agent-package-and-shim` (Phase 4, step 31) moved the
`ReportAgent` class itself into `deepear.src.agents.report.agent`, its methods
now execute in *that* module's namespace -- so this harness patches `Agent`
and `ForecastAgent` there, not on the `deepear.src.agents.report_agent` shim
(patching the shim would silently no-op: the class body would still read the
real `agno.agent.Agent` / `ForecastAgent` names from its own module globals).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import deepear.src.agents.report.agent as report_agent_module
from deepear.src.agents.report_agent import ReportAgent

# ---------------------------------------------------------------------------
# agno.models.base.Model stand-in
# ---------------------------------------------------------------------------


class FakeModel:
    """Minimal stand-in for agno.models.base.Model.

    `ReportAgent.__init__` only ever touches `hasattr(self.tool_model,
    'response_format')` (to decide whether the Planner agent gets an
    `output_schema`); nothing else on the model is read at construction time
    because `agno.agent.Agent` itself is faked (see `FakeAgent`).
    """

    id = "fake-model"

    def __init__(self, with_response_format: bool = False):
        if with_response_format:
            # Presence (not value) is what `hasattr` checks in report/agent.py.
            self.response_format = None


# ---------------------------------------------------------------------------
# agno.agent.Agent stand-in
# ---------------------------------------------------------------------------


class FakeRunResponse:
    """Minimal stand-in for agno's RunResponse: only `.content` is read."""

    def __init__(self, content: Any):
        self.content = content


class ScriptedAgentRouter:
    """Ordered (predicate, responder) rules shared across every `FakeAgent`.

    `ReportAgent` builds four internal `Agent` instances (planner, writer,
    editor, section_editor) that all get swapped for `FakeAgent` when `Agent`
    is monkeypatched module-wide. Rather than threading per-instance scripts
    through `ReportAgent.__init__` (which we do not control), every `FakeAgent`
    built off the same router dispatches on the *prompt text* it receives --
    mirroring the pattern in test_report_agent_citations.py, which dispatches
    on distinctive substrings produced by `deepear.src.prompts.report_agent`.
    """

    def __init__(self):
        self._rules: list[tuple[Callable[[str], bool], Any]] = []
        self.calls: list[str] = []

    def when_contains(self, substring: str, responder: Any) -> "ScriptedAgentRouter":
        """Register a rule: if `substring` is in the prompt, use `responder`.

        `responder` is either a plain string (returned as-is) or a callable
        taking the full prompt and returning a string (or raising, to
        characterize failure paths).
        """
        self._rules.append((lambda prompt: substring in prompt, responder))
        return self

    def resolve(self, prompt: str) -> str:
        self.calls.append(prompt)
        for predicate, responder in self._rules:
            if predicate(prompt):
                if callable(responder):
                    return responder(prompt)
                return responder
        # No rule matched: mirrors the seed test's fallback ("" for anything
        # the script did not anticipate) rather than raising, since a real
        # agno Agent would always return *something*.
        return ""


def raising(exc: BaseException) -> Callable[[str], str]:
    """Build a router/run_fn responder that always raises `exc` when called."""

    def _raise(_prompt: str) -> str:
        raise exc

    return _raise


class FakeAgent:
    """Minimal stand-in for agno.agent.Agent.

    Construction accepts and stores arbitrary kwargs (model, tools,
    instructions, markdown, debug_mode, output_schema, ...) exactly like the
    real `Agent`, and exposes `.instructions` as a plain mutable attribute
    since `ReportAgent` reassigns it per call (e.g. `self.planner.instructions
    = [instruction]`).

    Two ways to script `.run(prompt)`:
    - `run_fn`: a direct callable, for standalone tests of
      `_run_agent_with_retry` that build a `FakeAgent` without going through
      `ReportAgent.__init__` at all.
    - `router`: a shared `ScriptedAgentRouter`, for tests that build a real
      `ReportAgent` via `make_report_agent` and need its four internal agents
      to dispatch consistently.
    """

    def __init__(
        self,
        run_fn: Optional[Callable[[str], Any]] = None,
        router: Optional[ScriptedAgentRouter] = None,
        **kwargs: Any,
    ):
        self.kwargs = kwargs
        self.instructions = kwargs.get("instructions", [])
        self._run_fn = run_fn
        self._router = router
        self.calls: list[str] = []

    def run(self, prompt: str) -> FakeRunResponse:
        self.calls.append(prompt)
        if self._run_fn is not None:
            content = self._run_fn(prompt)
        elif self._router is not None:
            content = self._router.resolve(prompt)
        else:
            content = ""
        return FakeRunResponse(content)


def make_scripted_agent_class(router: ScriptedAgentRouter) -> type:
    """Build a `FakeAgent` subclass bound to `router`, suitable for
    `monkeypatch.setattr(report_agent_module, "Agent", <this class>)`.
    """

    class _RoutedFakeAgent(FakeAgent):
        def __init__(self, **kwargs: Any):
            super().__init__(router=router, **kwargs)

    return _RoutedFakeAgent


# ---------------------------------------------------------------------------
# ForecastAgent stand-in (kept out of the way unless a test opts in)
# ---------------------------------------------------------------------------


class FakeForecastAgent:
    """Stand-in for deepear.src.agents.forecast_agent.ForecastAgent.

    Built by `make_fake_forecast_agent_class`, which also hands back a
    construction counter so tests can assert how many times the *real*
    `ReportAgent._get_forecast_agent` lazy-cache actually constructed one of
    these, independent of how many times `_get_forecast_agent()` itself is
    called (it is designed to be called repeatedly and cheaply once cached).
    """

    def __init__(self, db: Any, model: Any, forecast_result: Any = None):
        self.db = db
        self.model = model
        self._forecast_result = forecast_result
        self.calls: list[dict] = []

    def generate_forecast(
        self,
        ticker: str,
        related_signals: list,
        pred_len: int = 5,
        extra_context: str = "",
    ) -> Any:
        self.calls.append(
            {
                "ticker": ticker,
                "pred_len": pred_len,
                "related_signals": related_signals,
                "extra_context": extra_context,
            }
        )
        result = self._forecast_result
        if callable(result):
            return result(ticker, pred_len)
        return result


def make_fake_forecast_agent_class(forecast_result: Any = None) -> tuple[type, dict]:
    """Return (fake ForecastAgent class, construction counter dict).

    `construct_counter["count"]` increments once per `class(db, model)` call --
    i.e. once per real Kronos/ForecastAgent load that *would* have happened.
    `forecast_result` is either `None` (every forecast request is skipped, the
    current behavior when a forecast can't be produced), a `ForecastResult`-like
    value returned for every call, or a `(ticker, pred_len) -> value` callable.
    """
    construct_counter = {"count": 0}

    class _CountingFakeForecastAgent(FakeForecastAgent):
        def __init__(self, db: Any, model: Any):
            construct_counter["count"] += 1
            super().__init__(db, model, forecast_result=forecast_result)

    return _CountingFakeForecastAgent, construct_counter


# ---------------------------------------------------------------------------
# DatabaseManager stand-in
# ---------------------------------------------------------------------------


class FakeDatabaseManager:
    """In-memory stand-in for deepear.src.utils.database_manager.DatabaseManager.

    Implements exactly the surface `ReportAgent` touches: directly
    (`lookup_reference_by_url`, `execute_query` for the "sentiment" chart
    type), and via the `StockTools` collaborator `ReportAgent.generate_report`
    / `_process_charts` construct internally with `auto_update=False`
    (`get_stock_prices`, `save_stock_prices`, `search_stock`).
    """

    def __init__(
        self,
        references: Optional[dict] = None,
        sentiment_rows: Optional[list] = None,
        stock_prices: Any = None,
        search_results: Optional[list] = None,
    ):
        self._references = references or {}
        self._sentiment_rows = sentiment_rows if sentiment_rows is not None else []
        self._stock_prices = stock_prices
        self._search_results = search_results or []
        self.executed_queries: list[tuple] = []

    def lookup_reference_by_url(self, url: str) -> Optional[dict]:
        return self._references.get(url)

    def execute_query(self, query: str, params: tuple = ()) -> list:
        self.executed_queries.append((query, params))
        return list(self._sentiment_rows)

    def get_stock_prices(self, ticker: str, start_date: str, end_date: str):
        import pandas as pd

        if self._stock_prices is not None:
            return self._stock_prices
        return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume", "change_pct"])

    def save_stock_prices(self, ticker: str, df) -> None:
        pass

    def search_stock(self, query: str, limit: int = 5) -> list:
        return list(self._search_results)


# ---------------------------------------------------------------------------
# ReportAgent factory
# ---------------------------------------------------------------------------


@dataclass
class ReportAgentHarness:
    """Bundle of a real ReportAgent plus the fakes it was wired with."""

    agent: ReportAgent
    db: FakeDatabaseManager
    model: FakeModel
    tool_model: FakeModel
    router: ScriptedAgentRouter
    forecast_construct_counter: dict = field(default_factory=lambda: {"count": 0})


def make_report_agent(
    monkeypatch: Any,
    *,
    router: Optional[ScriptedAgentRouter] = None,
    db: Optional[FakeDatabaseManager] = None,
    model: Optional[FakeModel] = None,
    tool_model: Optional[FakeModel] = None,
    incremental_edit: bool = True,
    forecast_result: Any = None,
) -> ReportAgentHarness:
    """Build a real `ReportAgent` wired with fakes.

    Monkeypatches two construction-time collaborators in the
    `deepear.src.agents.report.agent` module namespace -- where `ReportAgent`
    itself now lives (since `finalize-report-agent-package-and-shim`), and
    where its methods actually resolve these names -- never via `sys.modules`
    replacement, following the seed test's convention:

    - `Agent` -> a `FakeAgent` subclass bound to `router`, so the four
      internal agents never make a real LLM call.
    - `ForecastAgent` -> a counting `FakeForecastAgent` subclass, so
      `ReportAgent._get_forecast_agent()`'s own (real, untouched) lazy-cache
      logic never loads the real, optionally Kronos-backed `ForecastAgent`.

    Requires the pytest `monkeypatch` fixture so both patches are reverted
    automatically at test teardown, regardless of pass/fail.
    """
    router = router or ScriptedAgentRouter()
    monkeypatch.setattr(report_agent_module, "Agent", make_scripted_agent_class(router))

    fake_forecast_cls, forecast_counter = make_fake_forecast_agent_class(forecast_result)
    monkeypatch.setattr(report_agent_module, "ForecastAgent", fake_forecast_cls)

    db = db if db is not None else FakeDatabaseManager()
    model = model if model is not None else FakeModel()
    tool_model = tool_model if tool_model is not None else model

    agent = ReportAgent(db, model, incremental_edit=incremental_edit, tool_model=tool_model)

    return ReportAgentHarness(
        agent=agent,
        db=db,
        model=model,
        tool_model=tool_model,
        router=router,
        forecast_construct_counter=forecast_counter,
    )
