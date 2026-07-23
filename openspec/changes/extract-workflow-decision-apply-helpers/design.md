## Context

`backtest/workflow_adapter.py:1395-1459` defines two `@staticmethod`s
already free of instance-state dependency: `_normalize_decision_for_portfolio`
clamps a raw portfolio-manager `Decision` to the shares actually
affordable/sellable given a `Portfolio`'s current cashflow/positions,
and `_update_portfolio_ticker` applies a (normalized) decision by
mutating the `Portfolio`'s cashflow and the ticker's shares/value in
place. Both are called from `run_single_day_with_precollected_signals`
via `self._normalize_decision_for_portfolio(...)` /
`self._update_portfolio_ticker(...)`, and directly by
`tests/test_workflow_adapter_smart_priority.py` via
`adapter._normalize_decision_for_portfolio(...)`.

## Goals / Non-Goals

**Goals:** move both functions verbatim into
`backtest/workflow/decision_apply.py`; keep both names resolvable as
`BacktestWorkflowAdapter` static methods (class- and instance-level
access) with zero call-site changes anywhere in `workflow_adapter.py`
or in tests.

**Non-Goals:** changing clamping/rounding behavior; changing the
`Portfolio`/`Decision`/`Position`/`Action` schema types these functions
construct (owned by `graph.schema`/`graph.constants`, imported locally
exactly as before).

## Decisions

1. **Plain `staticmethod(...)` assignment, not a `def` wrapper.**
   Because both functions are pure and already `@staticmethod`s with
   an identical call signature to what the module function needs
   (`(portfolio, ticker, decision)` — no `self`), a class-body
   assignment (`_normalize_decision_for_portfolio =
   staticmethod(decision_apply._normalize_decision_for_portfolio)`) is
   strictly simpler than a `def` delegator that just forwards
   arguments, and is indistinguishable from the original
   `@staticmethod def _normalize_decision_for_portfolio(...)` from any
   caller's perspective (`Class.name(...)` and `instance.name(...)`
   both work identically either way).
2. **Local imports stay local.** Both functions import
   `graph.constants`/`graph.schema` inside their bodies (not at
   `decision_apply.py`'s module top) — unchanged from the original,
   preserving the lazy-import style used throughout
   `workflow_adapter.py` to avoid eagerly pulling in DeepFund's graph
   package at `backtest.workflow_adapter` import time.

## Risks / Trade-offs

- None: two pure functions, zero monkeypatch coverage, verbatim move.
