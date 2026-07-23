## 1. Monkeypatch and call-site audit

- [x] 1.1 `git grep -n "load_or_compute_shared_phase1\|_build_shared_phase1_artifact" tests/ backtest/ deepfund/ runner/` — confirm `backtest/multi_personality_engine.py`'s `_load_shared_phase1_artifact` calls `shared_signal_adapter.load_or_compute_shared_phase1(trading_date=..., prices=..., max_workers=...)` on a real instance, and that `tests/test_multi_personality_day_orchestrator.py` has adapter subclasses that `super().load_or_compute_shared_phase1(...)` — both require the delegator to stay a genuine instance method.
- [x] 1.2 Confirm no class-attribute monkeypatch of either function name exists on `BacktestWorkflowAdapter`; confirm the two `backtest.workflow_adapter.SharedPhase1ArtifactCache.ARTIFACT_VERSION` / `backtest.workflow_adapter.BacktestWorkflowAdapter.SHARED_PHASE1_ARTIFACT_VERSION` class-attribute patches resolve against shared, re-exported class objects unaffected by this move.

## 2. Implementation

- [x] 2.1 Add `backtest/workflow/phase1_pipeline.py` with `_build_shared_phase1_artifact(adapter, trading_date, prices, enhanced_signals, phase1_input_metadata=None)` and `load_or_compute_shared_phase1(adapter, trading_date, prices, max_workers=5)`, moved verbatim with `self` -> `adapter`. Every internal call to another Phase-3-extracted delegator goes through `adapter.<name>(...)`.
- [x] 2.2 `backtest/workflow_adapter.py`: replace the two method bodies with delegators (`def _build_shared_phase1_artifact(self, ...): return phase1_pipeline._build_shared_phase1_artifact(self, ...)`, same pattern for `load_or_compute_shared_phase1`), both real `def` instance methods (not `staticmethod`) so subclass `super()` calls keep working.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/test_multi_personality_day_orchestrator.py tests/test_workflow_adapter_smart_priority.py tests/test_fof_engine.py -q` — all passed, 0 failed.
- [x] 3.2 `.venv_unified/bin/python -m pytest tests/ -q` — 945 passed, 10 skipped, 0 failed.
- [x] 3.3 `.venv_unified/bin/ruff check .` clean.
- [x] 3.4 `.venv_unified/bin/python run.py --check-env` exits 0.
