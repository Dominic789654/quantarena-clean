## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "SharedPhase1Artifact\|SharedPhase1ArtifactCache\|
  SharedAnalystSignalCache\|BacktestDecision" -- backtest/ tests/
  deepfund/ run*.py runner/` — hits in
  `backtest/multi_personality_engine.py` (plain import + type hints),
  `tests/test_multi_personality_day_orchestrator.py` (import +
  instantiation + two class-attribute monkeypatches),
  `tests/test_shared_phase_specialized_audit.py` (import +
  instantiation). All satisfied by re-import producing the same class
  objects.
- [x] 1.2 `git grep -n "monkeypatch\|patch(" tests/ | grep -iE
  "artifact_version|ARTIFACT_VERSION|SharedPhase1"` — two
  class-attribute patches at `test_multi_personality_day_orchestrator.
  py:694-695`, both targeting the string path
  `backtest.workflow_adapter.<ClassName>.<attr>`. Confirmed these
  resolve to the same class objects after the move (re-import, not a
  copy) — no delegator needed, the attribute lives on one class either
  way.

## 2. Implementation

- [x] 2.1 Add `backtest/workflow/__init__.py` (real package, matching
  the repo's no-namespace-packages convention).
- [x] 2.2 Add `backtest/workflow/decisions.py` with `BacktestDecision`
  moved verbatim.
- [x] 2.3 Add `backtest/workflow/phase1_artifact.py` with
  `SharedPhase1Artifact` and `SharedPhase1ArtifactCache` moved
  verbatim.
- [x] 2.4 Add `backtest/workflow/signal_cache.py` with
  `SharedAnalystSignalCache` moved verbatim.
- [x] 2.5 `backtest/workflow_adapter.py`: replace the four class bodies
  with `from backtest.workflow.decisions import BacktestDecision  #
  noqa: F401`, `from backtest.workflow.phase1_artifact import
  SharedPhase1Artifact, SharedPhase1ArtifactCache  # noqa: F401`, and
  `from backtest.workflow.signal_cache import SharedAnalystSignalCache
  # noqa: F401`, at the same source position.
- [x] 2.6 Drop now-unused module-level imports in
  `workflow_adapter.py` if any become dead (checked: `hashlib`, `json`,
  `os`, `UTC`/`datetime` are still used by `BacktestWorkflowAdapter`
  itself further down the file — no imports removed).

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` — 937 passed,
  10 skipped, 0 failed (baseline unchanged; no new tests in this
  change — the four classes already have coverage via
  `test_multi_personality_day_orchestrator.py`,
  `test_shared_phase_specialized_audit.py`, and the smart-priority
  adapter tests).
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
