## ADDED Requirements

### Requirement: BacktestWorkflowAdapter and create_workflow_adapter are defined in backtest/workflow/adapter.py
`backtest/workflow/adapter.py` SHALL define `BacktestWorkflowAdapter` (with its `__init__`, `_adopt_prev_portfolio`, `_build_api_source_config`, `run_single_day`, `run_single_day_with_precollected_signals`, `run_single_day_with_smart_priority`, `get_current_portfolio`, `close`, `__enter__`, `__exit__`, `__del__`, and every same-named delegator method to `backtest.workflow.{scoring,decision_apply,db_store,company_news_signature,signal_collection,phase1_pipeline}`) and `create_workflow_adapter`, importable independently of `backtest.workflow_adapter`.

#### Scenario: The class is importable directly from its new home
- **WHEN** `from backtest.workflow.adapter import BacktestWorkflowAdapter, create_workflow_adapter` is executed without first importing `backtest.workflow_adapter`
- **THEN** the import succeeds and `BacktestWorkflowAdapter` can be instantiated and used exactly as before this change

### Requirement: backtest/workflow_adapter.py re-exports every name previously importable from it
`backtest/workflow_adapter.py` SHALL be a compatibility shim that re-exports `BacktestWorkflowAdapter`, `BacktestDecision`, `SharedPhase1Artifact`, `SharedPhase1ArtifactCache`, `SharedAnalystSignalCache`, `create_workflow_adapter`, and `logger`, such that `from backtest.workflow_adapter import <Name>` for each of these names keeps resolving to the exact same object it resolved to before this change.

#### Scenario: Existing import statements keep working unchanged
- **WHEN** `from backtest.workflow_adapter import BacktestWorkflowAdapter` (or `BacktestDecision`, or `create_workflow_adapter`, or `SharedPhase1Artifact`) is executed
- **THEN** the imported object is identical (`is`) to the object obtained via `from backtest.workflow.adapter import BacktestWorkflowAdapter` (respectively `from backtest.workflow.decisions import BacktestDecision`, etc.)

### Requirement: Class-attribute monkeypatches via the backtest.workflow_adapter string path keep mutating the real class objects
Monkeypatching a class attribute through the string path `backtest.workflow_adapter.<ClassName>.<attr>` (for `SharedPhase1ArtifactCache` and `BacktestWorkflowAdapter`) SHALL mutate the same class object reachable via `backtest.workflow.phase1_artifact.SharedPhase1ArtifactCache` / `backtest.workflow.adapter.BacktestWorkflowAdapter` respectively, and code inside `backtest/workflow/adapter.py` reading that attribute (e.g. `adapter.SHARED_PHASE1_ARTIFACT_VERSION`, `SharedPhase1ArtifactCache.PRIORITY_SCORE_VERSION`) SHALL observe the patched value.

#### Scenario: Patching SHARED_PHASE1_ARTIFACT_VERSION via the old module path is observed by adapter.py's own code
- **WHEN** `monkeypatch.setattr("backtest.workflow_adapter.BacktestWorkflowAdapter.SHARED_PHASE1_ARTIFACT_VERSION", "v3")` is applied and a new `BacktestWorkflowAdapter` instance's phase1 artifact is built
- **THEN** the built artifact's `metadata["artifact_version"]` equals `"v3"`

### Requirement: Patching backtest.workflow_adapter.logger.info is observed by every logger.info call inside backtest/workflow/adapter.py
`backtest/workflow_adapter.py` SHALL expose `logger` as a module attribute bound to the same `loguru` singleton object that `backtest/workflow/adapter.py` uses for its own logging calls, so that `monkeypatch.setattr('backtest.workflow_adapter.logger.info', fake)` causes every `logger.info(...)` call made from within `backtest/workflow/adapter.py` (e.g. inside `run_single_day_with_precollected_signals`) to invoke `fake` instead of the original method.

#### Scenario: A logger.info patch via the shim's module path intercepts adapter.py's real logging calls
- **WHEN** `monkeypatch.setattr('backtest.workflow_adapter.logger.info', fake_info)` is applied and `BacktestWorkflowAdapter.run_single_day_with_precollected_signals` is called (which logs via `logger.info(...)` inside `backtest/workflow/adapter.py`)
- **THEN** `fake_info` is invoked with the same messages the original `logger.info` would have received

### Requirement: backtest/__init__.py's lazy re-exports keep resolving BacktestWorkflowAdapter, BacktestDecision, and create_workflow_adapter
`backtest/__init__.py`'s module-level `__getattr__` SHALL continue to resolve `backtest.BacktestWorkflowAdapter`, `backtest.BacktestDecision`, and `backtest.create_workflow_adapter` by importing `backtest.workflow_adapter` and reading the corresponding attribute off it, unchanged by this move.

#### Scenario: Lazy top-level re-export still works
- **WHEN** `import backtest; backtest.BacktestWorkflowAdapter` is accessed
- **THEN** it resolves without error to the same class as `backtest.workflow.adapter.BacktestWorkflowAdapter`
