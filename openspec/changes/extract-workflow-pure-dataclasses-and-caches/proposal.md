## Why

`backtest/workflow_adapter.py` (1981 lines) is the Phase 3 target of the
decomposition program (docs/refactor_program_plan.md Phase 3, step 1 of
4 in this first batch). Its first ~320 lines are two pure dataclasses
and two self-contained, file-backed cache classes with no dependency on
`BacktestWorkflowAdapter` instance state — the lowest-risk extraction in
the file. Moving them into a real `backtest/workflow/` package starts
the package and establishes the re-export convention the remaining
three changes in this batch (scoring, decision-apply helpers, db store)
build on.

## What Changes

- Add `backtest/workflow/` package (`backtest/workflow/__init__.py`,
  real package per Phase 2 convention — the repo does not use namespace
  packages).
- Add `backtest/workflow/decisions.py` holding `BacktestDecision` (moved
  verbatim, lines ~33-41).
- Add `backtest/workflow/phase1_artifact.py` holding
  `SharedPhase1Artifact` (moved verbatim, lines ~44-119) and
  `SharedPhase1ArtifactCache` (moved verbatim, lines ~122-253) — grouped
  together because the cache class's public API (`load`/`save`) takes
  and returns `SharedPhase1Artifact` instances and both share the
  `_prices_signature`/`_signature` signature helpers that
  `workflow_adapter.py`'s own methods call directly
  (`SharedPhase1ArtifactCache._prices_signature(...)`) — splitting them
  into separate modules would force a cross-module import for no
  benefit.
- Add `backtest/workflow/signal_cache.py` holding
  `SharedAnalystSignalCache` (moved verbatim, lines ~256-343) — kept
  separate from `phase1_artifact.py` because it caches a different,
  unrelated unit (per-ticker-per-analyst raw signals, not the day-level
  artifact) and has its own independent `_entry_path` layout.
- `backtest/workflow_adapter.py` re-imports all four names with
  `from backtest.workflow.<module> import <Name>  # noqa: F401` at the
  same module position the class definitions used to occupy, so
  `from backtest.workflow_adapter import SharedPhase1Artifact` (used by
  `backtest/multi_personality_engine.py:34` and
  `tests/test_multi_personality_day_orchestrator.py`), `from backtest.
  workflow_adapter import BacktestDecision`, and
  `backtest/__init__.py`'s lazy re-exports (`BacktestDecision`,
  `BacktestWorkflowAdapter`, `create_workflow_adapter` all resolve
  through `backtest.workflow_adapter`) keep working unchanged.
- `BacktestWorkflowAdapter.SHARED_PHASE1_ARTIFACT_VERSION` keeps reading
  `SharedPhase1ArtifactCache.ARTIFACT_VERSION` — same class object after
  the move, so `monkeypatch.setattr("backtest.workflow_adapter.
  SharedPhase1ArtifactCache.ARTIFACT_VERSION", "v3")` in
  `tests/test_multi_personality_day_orchestrator.py:694` still mutates
  the one class attribute that every reference (adapter, cache
  instances, re-export) shares.
- No behavior change: identical class bodies, identical serialization
  format, identical cache file layout.

## Capabilities

### New Capabilities
- `workflow-pure-dataclasses-and-caches`: the `BacktestDecision`
  dataclass, the `SharedPhase1Artifact` dataclass and its versioned
  `SharedPhase1ArtifactCache`, and the standalone
  `SharedAnalystSignalCache` — all pure/self-contained state used by the
  backtest workflow adapter.

### Modified Capabilities
- None.

## Impact

- New `backtest/workflow/__init__.py`, `backtest/workflow/decisions.py`,
  `backtest/workflow/phase1_artifact.py`,
  `backtest/workflow/signal_cache.py`. Modified
  `backtest/workflow_adapter.py` (class bodies replaced by re-imports).
- Monkeypatch audit (ground rule 3):
  `git grep -n "SharedPhase1Artifact\|SharedPhase1ArtifactCache\|
  SharedAnalystSignalCache\|BacktestDecision" -- backtest/ tests/
  deepfund/ run*.py runner/` shows: `backtest/multi_personality_engine.
  py:34` does `from backtest.workflow_adapter import
  SharedPhase1Artifact, create_workflow_adapter` (plain import, three
  more bare-type-hint usages further down the file) — satisfied by the
  re-export. `tests/test_multi_personality_day_orchestrator.py` does
  `from backtest.workflow_adapter import BacktestWorkflowAdapter,
  SharedPhase1Artifact` (import) and constructs `SharedPhase1Artifact(
  ...)` instances directly (line ~71) — satisfied by the re-export
  producing the same class object.
  `tests/test_shared_phase_specialized_audit.py` does `from backtest.
  workflow_adapter import BacktestDecision` and constructs instances —
  satisfied.
  `git grep -n "monkeypatch\|patch(" tests/ | grep -iE
  "artifact_version|ARTIFACT_VERSION|SharedPhase1"` finds two class-
  attribute patches in `tests/test_multi_personality_day_orchestrator.
  py:694-695`: `monkeypatch.setattr("backtest.workflow_adapter.
  SharedPhase1ArtifactCache.ARTIFACT_VERSION", "v3")` and `monkeypatch.
  setattr("backtest.workflow_adapter.BacktestWorkflowAdapter.
  SHARED_PHASE1_ARTIFACT_VERSION", "v3")`. Both target the string path
  `backtest.workflow_adapter.SharedPhase1ArtifactCache` — after the
  move, `backtest.workflow_adapter.SharedPhase1ArtifactCache` still
  resolves (via the re-import) to the *same class object* defined in
  `backtest.workflow.phase1_artifact`, so `monkeypatch.setattr` mutates
  the one shared `ARTIFACT_VERSION` class attribute regardless of which
  module path is used to reach the class — verified by re-running the
  test after the move (ground rule 3's "class-attribute patches survive
  moves as long as a same-named delegator stays on the class" applies
  here even more directly: it is the *same class*, not a delegator).
