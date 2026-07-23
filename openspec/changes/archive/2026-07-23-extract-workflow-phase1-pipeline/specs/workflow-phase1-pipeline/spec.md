## ADDED Requirements

### Requirement: load_or_compute_shared_phase1 attempts a signature-keyed cache load before falling back to parallel signal collection
`backtest.workflow.phase1_pipeline.load_or_compute_shared_phase1(adapter, trading_date, prices, max_workers=5)` SHALL, when `adapter.shared_phase1_artifact_cache` is not `None`, resolve an input signature via `adapter._build_phase1_prefetched_analyst_inputs` and `adapter._resolve_phase1_input_metadata`, attempt `adapter.shared_phase1_artifact_cache.load(...)` keyed on that signature, and return the loaded artifact (with `prices` refreshed and `metadata["cache_hit"]` set to `True`) without calling `adapter.collect_signals_only_parallel_v2` when the load succeeds.

#### Scenario: A cache hit skips signal collection entirely
- **WHEN** `adapter.shared_phase1_artifact_cache.load(...)` returns a non-`None` artifact for the resolved signature
- **THEN** `load_or_compute_shared_phase1` returns that artifact with `metadata["cache_hit"] is True` and does not call `adapter.collect_signals_only_parallel_v2`

### Requirement: A cache miss or disabled cache falls back to parallel signal collection and builds a fresh artifact
`backtest.workflow.phase1_pipeline.load_or_compute_shared_phase1` SHALL, when the cache is disabled (`adapter.shared_phase1_artifact_cache is None`), when signature resolution raises, or when the cache load returns `None`, call `adapter.collect_signals_only_parallel_v2(trading_date, prices, max_workers, prefetched_analyst_inputs=...)` and build a fresh artifact via `adapter._build_shared_phase1_artifact(...)`.

#### Scenario: Cache miss falls back to parallel collection
- **WHEN** `adapter.shared_phase1_artifact_cache.load(...)` returns `None`
- **THEN** `load_or_compute_shared_phase1` calls `adapter.collect_signals_only_parallel_v2` and returns a freshly built `SharedPhase1Artifact`

#### Scenario: Signature resolution failure bypasses the cache without raising
- **WHEN** `adapter._resolve_phase1_input_metadata` raises an exception
- **THEN** `load_or_compute_shared_phase1` logs a warning, treats the cache as disabled for this call, and still returns a freshly built artifact via parallel collection

### Requirement: A freshly built artifact is persisted to the cache when the cache is enabled
`backtest.workflow.phase1_pipeline.load_or_compute_shared_phase1` SHALL, after building a fresh artifact and when the cache is enabled, call `adapter.shared_phase1_artifact_cache.save(...)` with the same signature used for the load attempt, and SHALL still return the artifact even if the save call raises.

#### Scenario: Cache save failure does not prevent the artifact from being returned
- **WHEN** `adapter.shared_phase1_artifact_cache.save(...)` raises an exception
- **THEN** `load_or_compute_shared_phase1` logs a warning and still returns the freshly built artifact

### Requirement: _build_shared_phase1_artifact constructs a SharedPhase1Artifact from adapter state and the computed priority order
`backtest.workflow.phase1_pipeline._build_shared_phase1_artifact(adapter, trading_date, prices, enhanced_signals, phase1_input_metadata=None)` SHALL return a `SharedPhase1Artifact` whose `priority_order` is `adapter._get_smart_priority_order(enhanced_signals)` and whose `metadata` includes `adapter.market`, `adapter.tickers`, `adapter.analysts`, `adapter.llm_provider`, `adapter.llm_model`, `adapter.SHARED_PHASE1_ARTIFACT_VERSION`, and any keys from `phase1_input_metadata`, with `phase1_input_metadata` keys taking precedence over the function's own defaults.

#### Scenario: Metadata reflects current adapter configuration
- **WHEN** `_build_shared_phase1_artifact(adapter, trading_date, prices, enhanced_signals)` is called
- **THEN** the returned artifact's `metadata["market"]`, `metadata["tickers"]`, and `metadata["analysts"]` equal `adapter.market`, `list(adapter.tickers)`, and `list(adapter.analysts)` respectively

### Requirement: load_or_compute_shared_phase1 remains a genuine instance method reachable through subclass super() calls
`BacktestWorkflowAdapter` SHALL expose `load_or_compute_shared_phase1` and `_build_shared_phase1_artifact` as real `def` instance methods (not static methods or plain attribute assignments) that delegate to `backtest.workflow.phase1_pipeline`'s module functions, so that a subclass overriding `load_or_compute_shared_phase1` can call `super().load_or_compute_shared_phase1(...)` and reach the original behavior.

#### Scenario: A subclass override calling super() still reaches the real implementation
- **WHEN** a `BacktestWorkflowAdapter` subclass overrides `load_or_compute_shared_phase1` to add instrumentation and calls `super().load_or_compute_shared_phase1(trading_date, prices, max_workers=max_workers)`
- **THEN** the call returns the same `SharedPhase1Artifact` that calling `load_or_compute_shared_phase1` directly on a non-subclassed instance would return
