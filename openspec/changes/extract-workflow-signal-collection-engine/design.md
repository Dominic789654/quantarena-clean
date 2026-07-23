## Context

`backtest/workflow_adapter.py`'s signal-collection engine
(~lines 744-1139 before this change) is the smart-priority pipeline's
phase 1: for a given trading date and price map, collect every
configured analyst's signal for every ticker, in parallel, without
making any portfolio decision. `collect_signals_only_parallel_v2` is
the entry point: it builds a shared (read-only, per-call) `config`
dict and a serializable `portfolio_dict`, filters to tickers with a
known price, and submits one `_process_single_ticker_for_signals_v2`
call per ticker to a `ThreadPoolExecutor`. Each worker thread builds
its own `Portfolio`/`FundState` copy (no shared mutable state besides
the final write into the `signals` dict, which is `Lock`-guarded), runs
every valid analyst for its ticker (checking the shared-analyst-signal
file cache first via `_load_shared_analyst_signals`, saving fresh
results via `_save_shared_analyst_signals` when the analyst run
succeeded without any `[Error]`-tagged signal per `_signal_has_error`),
and returns an enhanced-signal dict with a computed priority score and
summary. `collect_signals_only` is a thin backward-compatibility
wrapper that calls `collect_signals_only_parallel_v2` and reshapes the
result into the older single-signal-per-ticker format.

This is the densest concentration of adapter instance-state reads in
the whole file: eleven distinct `self.*` attributes across the six
functions, plus five delegator methods already extracted in the two
preceding Phase 3 steps that these functions call into
(`_resolve_analyst_input_signature`, `_calculate_priority_score`,
`_signal_label`, `_calculate_signal_consistency`,
`_aggregate_signal_from_summary`).

## Goals / Non-Goals

**Goals:** move all six functions into
`backtest/workflow/signal_collection.py`, preserving the thread-pool
structure, the `Lock` scope, and both exception-handling layers
exactly; keep every `self.<name>(...)`/`adapter.<name>(...)` call site
working via same-named delegators; ensure the `ThreadPoolExecutor`
submission and every mutual call between the six functions (and to the
five delegators from earlier steps) goes through the adapter delegator,
never a bare module call.

**Non-Goals:** changing the thread-pool sizing, retry, or backoff
behavior; changing the shared-analyst-cache key derivation (still
delegated to `_resolve_analyst_input_signature`, untouched by this
step); changing `collect_signals_only`'s backward-compatible output
shape; touching `_calculate_priority_score` /
`_calculate_signal_consistency` / `_signal_label` /
`_aggregate_signal_from_summary` / `_get_smart_priority_order`
themselves (already extracted into `backtest/workflow/scoring.py` in
an earlier step — this step only changes how they are *called into*
from the newly-moved functions, replacing `self.<name>` with
`adapter.<name>`, which is the exact same call shape, just crossing a
module boundary now).

## Decisions

1. **Adapter-passing, consistent with the previous step.** Same
   rationale as `extract-workflow-company-news-signature-resolver`'s
   design.md: eleven `self.*` attributes read across six functions
   makes per-attribute parameter lifting unwieldy, and — more
   importantly — several of these functions are mutually recursive
   through adapter delegators (`_process_single_ticker_for_signals_v2`
   calls `_resolve_analyst_input_signature`,
   `_load_shared_analyst_signals`, `_save_shared_analyst_signals`,
   `_calculate_priority_score`, `_signal_label`,
   `_calculate_signal_consistency`; `collect_signals_only` calls
   `collect_signals_only_parallel_v2` and
   `_aggregate_signal_from_summary`; `collect_signals_only_parallel_v2`
   calls `_process_single_ticker_for_signals_v2` via the thread pool).
   Passing the adapter instance keeps every one of those calls as
   `adapter.<name>(...)`, identical in shape to the original
   `self.<name>(...)`, with no risk of missing an attribute at a call
   site that needs it.
2. **The `ThreadPoolExecutor.submit(...)` call site submits the bound
   delegator, not the bare module function.** This was the one
   genuinely new risk this step introduces relative to the previous
   two (which had no concurrency): if `submit(...)` were changed to
   call `signal_collection._process_single_ticker_for_signals_v2`
   directly (passing `adapter` as an explicit argument) instead of
   `adapter._process_single_ticker_for_signals_v2`, any future
   class-attribute patch of `_process_single_ticker_for_signals_v2`
   would silently stop reaching the worker threads. Verified
   experimentally (see proposal.md's Impact section): a
   class-attribute-patched fake was never invoked when the submission
   used the bare module function, and was invoked for every ticker
   once routed through the delegator.
3. **`Lock` stays function-local, not class- or module-level.** The
   original `signals_lock = Lock()` is created fresh on every call to
   `collect_signals_only_parallel_v2` (module function now), guarding
   only that call's own `signals` dict. This is unchanged — promoting
   it to module scope would introduce cross-call contention between
   concurrent `collect_signals_only_parallel_v2` invocations (e.g. two
   different adapters, or two calls on the same adapter from different
   threads) that does not exist today and is explicitly out of scope
   (ground rule 2: verbatim move).
4. **`_signal_has_error` keeps its original no-adapter `@staticmethod`
   signature** (never read instance state) — moved verbatim, exposed
   as `_signal_has_error = staticmethod(signal_collection._signal_has_error)`
   on the class, matching the `scoring.py`/`company_news_signature.py`
   convention for pure helpers.
5. **Full suite run twice, back to back, after landing.** Per the
   plan's explicit instruction for this step (thread-pool
   nondeterminism risk) and ground rule 1. Both runs: 945 passed, 10
   skipped, 0 failed (identical).

## Risks / Trade-offs

- This is the highest-risk step in the whole Phase 3 program per the
  plan; the two previous steps' discipline (adapter-passing,
  delegator-routing) is applied here without deviation, and the one
  genuinely new risk (thread-pool submission losing patchability) was
  identified, experimentally verified, and closed (decision 2).
- No behavior change; risk is purely "did every call site survive the
  move with identical semantics", closed by the two full-suite runs
  plus the targeted concurrency-sensitive test files
  (`test_workflow_adapter_smart_priority.py`,
  `test_multi_personality_day_orchestrator.py`, `test_fof_engine.py`,
  `test_shared_phase_specialized_audit.py`) run standalone first.
