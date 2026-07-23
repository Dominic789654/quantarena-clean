## Context

`backtest/workflow_adapter.py`'s shared phase1 pipeline (lines 624-740
before this change) is the cache-aside layer sitting directly on top of
the signal-collection engine extracted in the previous Phase 3 step.
`load_or_compute_shared_phase1` is the entry point called from
`run_single_day_with_smart_priority` (when a `shared_phase1_artifact_cache`
is configured) and from `backtest/multi_personality_engine.py`'s
`_load_shared_phase1_artifact` on real adapter instances shared across
personalities for the same trading day. It resolves an input signature
(delegating to `_build_phase1_prefetched_analyst_inputs` /
`_resolve_phase1_input_metadata`, both company-news-signature
delegators), attempts a cache load, and on a miss collects fresh
signals via `collect_signals_only_parallel_v2` before building a new
artifact via `_build_shared_phase1_artifact` and persisting it.
`_build_shared_phase1_artifact` is purely a `SharedPhase1Artifact`
constructor call that reads adapter state (`market`, `tickers`,
`analysts`, `llm_provider`, `llm_model`, `SHARED_PHASE1_ARTIFACT_VERSION`)
and calls `_get_smart_priority_order` (a scoring delegator).

## Goals / Non-Goals

**Goals:** move both functions into `backtest/workflow/phase1_pipeline.py`,
preserving the cache-aside control flow (signature resolution ->
cache load attempt -> collection fallback -> artifact build -> cache
save attempt) and both `try`/`except` layers (signature resolution
failure disables the cache for this call; cache load/save failures are
logged and treated as a miss) exactly; keep `load_or_compute_shared_phase1`
a genuine instance method (not merely an attribute) since
`tests/test_multi_personality_day_orchestrator.py` subclasses
`BacktestWorkflowAdapter` and calls `super().load_or_compute_shared_phase1(...)`.

**Non-Goals:** changing the cache-key derivation, the artifact schema,
or the fallback-to-parallel-collection behavior; touching
`SharedPhase1Artifact`/`SharedPhase1ArtifactCache` themselves (already
extracted); touching `collect_signals_only_parallel_v2` or the
company-news-signature delegators this step calls into (already
extracted in earlier steps — this step only changes how they are
*called into*, replacing `self.<name>` with `adapter.<name>`).

## Decisions

1. **Adapter-passing, consistent with every prior Phase 3 step.** Six
   distinct `adapter.*` reads across the two functions, plus mutual
   calls to four other delegators, make per-attribute parameter lifting
   unwieldy and error-prone; passing the adapter instance keeps every
   call site identical in shape to the original `self.<name>(...)`.
2. **`load_or_compute_shared_phase1` stays a real `def` instance method,
   not a `staticmethod` wrapper.** Every other Phase 3 delegator in this
   file is either a `staticmethod` (pure helpers) or a `def` method
   (adapter-state-dependent). This one must be the latter for a second
   reason beyond state access: `tests/test_multi_personality_day_orchestrator.py`
   defines adapter subclasses that override `load_or_compute_shared_phase1`
   and call `super().load_or_compute_shared_phase1(trading_date, prices,
   max_workers=max_workers)` to add instrumentation around the real
   implementation. A `staticmethod` or bare attribute assignment would
   not participate in the MRO the same way; a normal `def` delegator
   does, identically to the pre-move behavior.
3. **`SharedPhase1ArtifactCache.PRIORITY_SCORE_VERSION` /
   `SharedPhase1ArtifactCache._prices_signature(...)` keep their direct
   class references, not adapter-routed.** The original code already
   read these off the imported `SharedPhase1ArtifactCache` class object
   directly (not via `self`), so moving the calling function to a new
   module changes nothing about how these two are resolved — they are
   not adapter/instance state, and no test patches them independently
   of the class-attribute patches already accounted for (which mutate
   the class object itself, unaffected by which module calls into it).

## Risks / Trade-offs

- Low risk relative to the previous (signal-collection) step: no
  threading, no new concurrency surface. The one thing this step must
  get right is preserving `load_or_compute_shared_phase1` as a
  `super()`-reachable method, verified by running
  `tests/test_multi_personality_day_orchestrator.py` (which contains
  the subclassing tests) both standalone and as part of the full suite.
- No behavior change; risk is purely "did every call site and the MRO
  survive the move", closed by the full-suite run plus the targeted
  phase1/smart-priority test files run standalone first.
