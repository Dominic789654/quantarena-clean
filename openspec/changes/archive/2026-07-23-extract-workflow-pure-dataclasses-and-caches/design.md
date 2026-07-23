## Context

`backtest/workflow_adapter.py:33-343` defines, in order: `BacktestDecision`
(a plain `@dataclass`), `SharedPhase1Artifact` (a `@dataclass` with
serialize/restore classmethods), `SharedPhase1ArtifactCache` (a
versioned file cache keyed by trading date/market/tickers/analysts/
llm/prices/phase1-input-signature), and `SharedAnalystSignalCache` (a
simpler file cache keyed by trading date/market/ticker/analyst/llm).
None of the four reference `self` from `BacktestWorkflowAdapter` — they
are independently instantiable and already unit-testable in isolation.
`BacktestWorkflowAdapter` itself references
`SharedPhase1ArtifactCache.ARTIFACT_VERSION` (class attribute, line 358)
and calls `SharedPhase1ArtifactCache._prices_signature` /
`._signature` as class-level static helpers (lines 1141-1142, 1194)
from *outside* the cache class — those call sites stay in
`workflow_adapter.py` and keep working because the re-import binds the
same class object.

## Goals / Non-Goals

**Goals:** relocate the four classes into a real `backtest/workflow/`
package with a natural grouping; keep every existing import path,
lazy re-export, and class-attribute monkeypatch working; zero behavior
change.

**Non-Goals:** touching `BacktestWorkflowAdapter` itself (deferred to
later changes in this batch and to Phase 3 steps 18-22); changing the
cache file layout, versioning scheme, or serialization format;
splitting `SharedPhase1Artifact` from `SharedPhase1ArtifactCache` (see
grouping rationale in proposal.md).

## Decisions

1. **File grouping**: `decisions.py` (BacktestDecision only — it is
   unrelated to caching and is the return-type of the adapter's public
   `run_single_day*` methods, worth keeping separately importable
   without pulling in cache code); `phase1_artifact.py`
   (`SharedPhase1Artifact` + `SharedPhase1ArtifactCache`, coupled by a
   shared serialization contract and shared static signature helpers);
   `signal_cache.py` (`SharedAnalystSignalCache`, a structurally similar
   but domain-independent cache). This matches the module names
   specified in docs/refactor_program_plan.md's Phase 3 execution brief.
2. **Squashed single commit**: per the plan, this is "one squashed PR"
   covering all four classes rather than four incremental steps — the
   classes have no interdependency risk that would benefit from
   splitting further, and grouping them avoids three intermediate
   commits that would each leave `workflow_adapter.py` in a
   half-migrated state for no test-safety benefit.
3. **Re-import, not re-export shim function**: `workflow_adapter.py`
   uses a plain `from backtest.workflow.<module> import <Name>  # noqa:
   F401` for each of the four names, at the same source position the
   class body used to start. This is sufficient (not a `_shim`-style
   indirection) because ground rule 3 only requires shimming when an
   *internal caller* inside the moved code calls back into the
   defining module by bare name — none of these four classes call back
   into `BacktestWorkflowAdapter` or any other name still living in
   `workflow_adapter.py`.
4. **`BacktestWorkflowAdapter.SHARED_PHASE1_ARTIFACT_VERSION =
   SharedPhase1ArtifactCache.ARTIFACT_VERSION`** stays a class-body
   assignment evaluated once at class-definition time, unchanged. This
   is intentionally *not* rewritten to a property — `monkeypatch.
   setattr(..., "ARTIFACT_VERSION", "v3")` in
   `test_multi_personality_day_orchestrator.py:694` mutates
   `SharedPhase1ArtifactCache`'s attribute after
   `BacktestWorkflowAdapter` has already been defined and its own
   `SHARED_PHASE1_ARTIFACT_VERSION` copied the *original* value at
   import time; the test's companion patch at line 695
   (`monkeypatch.setattr("backtest.workflow_adapter.
   BacktestWorkflowAdapter.SHARED_PHASE1_ARTIFACT_VERSION", "v3")`)
   patches the adapter's own copy separately — this dual-patch pattern
   is unchanged by the move (verified: same class object, same
   attribute-copy-at-class-definition-time semantics as before).

## Risks / Trade-offs

- None material: verbatim moves of self-contained classes; the only
  cross-module coupling (`BacktestWorkflowAdapter` reading
  `SharedPhase1ArtifactCache`'s class attribute and static methods) is
  preserved by the re-import producing the identical class object.
