# workflow-pure-dataclasses-and-caches Specification

## Purpose
TBD - created by archiving change extract-workflow-pure-dataclasses-and-caches. Update Purpose after archive.
## Requirements
### Requirement: BacktestDecision container
`backtest.workflow.decisions.BacktestDecision` SHALL be a dataclass holding `ticker`, `action`, `shares`, `price`, `justification`, and `analyst_signals`, matching the field set and types previously defined inline in `backtest/workflow_adapter.py`.

#### Scenario: Decision constructed with all fields
- **WHEN** `BacktestDecision(ticker="AAA", action="BUY", shares=10, price=1.0, justification="x", analyst_signals={})` is constructed
- **THEN** all six fields are accessible as attributes with the values passed in

### Requirement: SharedPhase1Artifact serialization round-trips
`backtest.workflow.phase1_artifact.SharedPhase1Artifact.to_payload` and `.from_payload` SHALL round-trip `trading_date`, `prices`, `enhanced_signals` (including nested `analyst_signals` lists converted via `model_dump`/`AnalystSignal.model_validate`), `priority_order`, and `metadata`, and `.from_payload` SHALL return `None` when the payload is missing required keys or has the wrong types.

#### Scenario: Round-trip preserves artifact fields
- **WHEN** an artifact's `to_payload()` output is passed to `SharedPhase1Artifact.from_payload(...)`
- **THEN** the resulting artifact has the same `trading_date`, `prices`, `priority_order`, and equivalent `enhanced_signals`

#### Scenario: Malformed payload returns None
- **WHEN** `from_payload` receives a dict missing `trading_date` or with `prices` not a dict
- **THEN** it returns `None` instead of raising

### Requirement: SharedPhase1ArtifactCache versioned load/save
`backtest.workflow.phase1_artifact.SharedPhase1ArtifactCache` SHALL persist and retrieve `SharedPhase1Artifact` instances keyed by a deterministic path derived from trading date, market, tickers, analysts, LLM provider/model, prices, and an explicit phase1-input signature, tagging saved and loaded artifacts' metadata with its `ARTIFACT_VERSION` and `PRIORITY_SCORE_VERSION` class attributes.

#### Scenario: Save then load returns an equivalent artifact
- **WHEN** `cache.save(...)` is called with an artifact and then `cache.load(...)` is called with the same key arguments
- **THEN** the loaded artifact's `prices`, `enhanced_signals`, and `priority_order` match, and its metadata has `cache_hit=True`

#### Scenario: Missing cache entry returns None
- **WHEN** `cache.load(...)` is called for a key with no prior `save(...)`
- **THEN** it returns `None` without raising

### Requirement: SharedAnalystSignalCache per-ticker-per-analyst caching
`backtest.workflow.signal_cache.SharedAnalystSignalCache` SHALL persist and retrieve lists of `AnalystSignal` objects keyed by trading date, market, ticker, analyst key, LLM provider/model, and an optional input signature, returning `None` from `load` when the cache file is missing, unreadable, or contains an item that fails `AnalystSignal.model_validate`.

#### Scenario: Save then load returns equivalent signals
- **WHEN** `cache.save(...)` is called with a list of `AnalystSignal` instances and then `cache.load(...)` is called with the same key arguments
- **THEN** the loaded list has the same length and each signal's `model_dump()` matches the original

#### Scenario: Invalid cache item invalidates the whole entry
- **WHEN** the cached file's `analyst_signals` list contains an item that fails `AnalystSignal.model_validate`
- **THEN** `load` returns `None` for that entry

### Requirement: workflow_adapter re-exports pure dataclasses and caches
`backtest/workflow_adapter.py` SHALL expose `BacktestDecision`, `SharedPhase1Artifact`, `SharedPhase1ArtifactCache`, and `SharedAnalystSignalCache` as module attributes re-imported from `backtest.workflow.decisions`, `backtest.workflow.phase1_artifact`, and `backtest.workflow.signal_cache`, so existing `from backtest.workflow_adapter import <Name>` imports, `backtest/__init__.py`'s lazy re-exports, and `monkeypatch.setattr("backtest.workflow_adapter.SharedPhase1ArtifactCache.ARTIFACT_VERSION", ...)` continue to resolve against the same class objects.

#### Scenario: Existing import path keeps working
- **WHEN** `backtest/multi_personality_engine.py` runs `from backtest.workflow_adapter import SharedPhase1Artifact, create_workflow_adapter`
- **THEN** the import succeeds and `SharedPhase1Artifact` is the same class object defined in `backtest.workflow.phase1_artifact`

#### Scenario: Class-attribute monkeypatch still mutates shared state
- **WHEN** a test does `monkeypatch.setattr("backtest.workflow_adapter.SharedPhase1ArtifactCache.ARTIFACT_VERSION", "v3")`
- **THEN** any `SharedPhase1ArtifactCache` instance (constructed via either the re-exported or the canonical import path) observes `ARTIFACT_VERSION == "v3"` for the duration of the test

