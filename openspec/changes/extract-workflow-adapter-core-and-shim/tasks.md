## 1. Audit

- [x] 1.1 `git grep -n "backtest.workflow_adapter" -- backtest/ tests/ runner/ deepfund/` — classify every hit: plain imports (satisfied by re-export), the two class-attribute patches on `SharedPhase1ArtifactCache.ARTIFACT_VERSION` / `BacktestWorkflowAdapter.SHARED_PHASE1_ARTIFACT_VERSION` (mutate shared class objects, unaffected by the move), and the one `logger.info` singleton-attribute patch (requires the shim to keep exposing `logger`, not a `sys.modules` indirection case).
- [x] 1.2 `git grep -n "from backtest.workflow_adapter import\|from backtest import" tests/ backtest/ runner/` — confirm every imported name (`BacktestWorkflowAdapter`, `BacktestDecision`, `SharedPhase1Artifact`, `create_workflow_adapter`) is covered by the shim's re-export list.
- [x] 1.3 Read `backtest/__init__.py`'s `_EXPORTS` lazy-import table; confirm its `("backtest.workflow_adapter", "BacktestWorkflowAdapter")` / `("backtest.workflow_adapter", "BacktestDecision")` / `("backtest.workflow_adapter", "create_workflow_adapter")` entries resolve via `importlib.import_module` + `getattr`, which works identically against a re-exporting shim module.
- [x] 1.4 Confirm no `backtest/workflow/*.py` submodule imports `backtest.workflow_adapter` or `backtest.workflow.adapter` (no circular-import risk from the new module).

## 2. Implementation

- [x] 2.1 Add `backtest/workflow/adapter.py`: move `BacktestWorkflowAdapter` and `create_workflow_adapter` verbatim, with their own copies of every import the class body/factory needs, including the module-level `setup_paths()` and `load_dotenv(get_project_root() / ".env")` side-effecting calls.
- [x] 2.2 Collapse `backtest/workflow_adapter.py` to a compatibility-shim docstring plus: `from loguru import logger`, `from backtest.workflow.decisions import BacktestDecision`, `from backtest.workflow.phase1_artifact import SharedPhase1Artifact, SharedPhase1ArtifactCache`, `from backtest.workflow.signal_cache import SharedAnalystSignalCache`, `from backtest.workflow.adapter import BacktestWorkflowAdapter, create_workflow_adapter`.
- [x] 2.3 Experimentally verify the `logger` re-export must be the same singleton object (ground rule 3 discipline): temporarily replace the shim's `from loguru import logger` with a decoy object, rerun the `logger.info`-patching test, confirm it fails (patched `.info` never observed); revert and confirm it passes again.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/test_multi_personality_day_orchestrator.py tests/test_workflow_adapter_smart_priority.py tests/test_fof_engine.py tests/test_workflow_run_single_day.py tests/test_db_connection_cleanup.py tests/test_personality_aliases.py tests/test_backtest_api_source_config.py tests/test_shared_phase_specialized_audit.py -q` — all passed, 0 failed.
- [x] 3.2 `.venv_unified/bin/python -m pytest tests/ -q` run **twice**, back to back (per the plan's instruction for this step, since it moves threaded orchestration) — both runs 945 passed, 10 skipped, 0 failed.
- [x] 3.3 `.venv_unified/bin/ruff check .` clean.
- [x] 3.4 `.venv_unified/bin/python run.py --check-env` exits 0.
- [x] 3.5 Record final `backtest/workflow_adapter.py` line count in the commit message.
