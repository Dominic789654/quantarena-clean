## Why

Phase 3 step 18 (docs/refactor_program_plan.md). `_stable_json_signature`,
`_normalize_news_item`, `_get_company_news_signature_payload`,
`_get_prefetched_analyst_payload`, `_ensure_company_news_prefetched_payload`,
`_build_phase1_prefetched_analyst_inputs`, `_resolve_analyst_input_signature`,
and `_resolve_phase1_input_metadata` are the cache-invalidation signature
plumbing that lets the shared analyst-signal cache and the shared phase-1
artifact cache detect when a ticker's company-news input has changed and
must be recomputed rather than served stale. Three of the eight read
`self.market`, `self.api_source`, and/or `self.analysts` from the adapter
instance, so extracting them requires either lifting those three attributes
into positional parameters at every call site (including the mutual calls
between these eight functions and the call from
`_process_single_ticker_for_signals_v2`), or passing the adapter instance
itself. This change passes the adapter instance, because
`tests/test_workflow_adapter_smart_priority.py` monkeypatches
`_get_company_news_signature_payload` as a **class attribute** on
`BacktestWorkflowAdapter` in three tests, and that patch must keep
propagating through every internal caller.

## What Changes

- Add `backtest/workflow/company_news_signature.py` with the eight
  functions, moved verbatim except for the mandated adapter-passing:
  - `_stable_json_signature(payload)`, `_normalize_news_item(news_item)`,
    and `_get_prefetched_analyst_payload(prefetched_analyst_data,
    analyst_key)` keep their original no-adapter, no-self signatures
    (they never read instance state).
  - `_get_company_news_signature_payload(adapter, trading_date, ticker)`,
    `_ensure_company_news_prefetched_payload(adapter, trading_date, ticker,
    prefetched_analyst_data=None)`,
    `_build_phase1_prefetched_analyst_inputs(adapter, trading_date, prices)`,
    `_resolve_analyst_input_signature(adapter, trading_date, ticker,
    analyst_key, prefetched_analyst_data=None)`, and
    `_resolve_phase1_input_metadata(adapter, trading_date, prices,
    prefetched_analyst_inputs=None)` take the adapter instance as their
    first parameter (named `adapter`, replacing `self`).
  - Every call from one of these eight functions to another goes through
    `adapter.<name>(...)` (the class-attribute-patchable delegator on
    `BacktestWorkflowAdapter`), never a direct
    `company_news_signature.<name>(...)` module call, so the
    `_get_company_news_signature_payload` class-attribute monkeypatch
    keeps propagating through every internal caller.
- `BacktestWorkflowAdapter` keeps same-named delegator methods for all
  eight names: three (`_stable_json_signature`, `_normalize_news_item`,
  `_get_prefetched_analyst_payload`) as direct `staticmethod(...)` class
  attribute assignments (matching the `scoring`/`decision_apply` module
  convention already established in this file), and five
  (`_get_company_news_signature_payload`,
  `_ensure_company_news_prefetched_payload`,
  `_build_phase1_prefetched_analyst_inputs`,
  `_resolve_analyst_input_signature`, `_resolve_phase1_input_metadata`) as
  `def` instance methods that call the module function with `self` as the
  `adapter` argument.
- No test/production behavior change; this is a pure code-motion +
  parameter-lifting change.

## Capabilities

### New Capabilities
- `workflow-company-news-signature`: the company-news cache-invalidation
  signature resolver used by the shared analyst-signal cache and the
  shared phase-1 artifact cache.

### Modified Capabilities
- None.

## Impact

- New `backtest/workflow/company_news_signature.py`. Modified
  `backtest/workflow_adapter.py` (eight method bodies replaced by
  delegators calling the module functions with `self` passed as the
  `adapter` argument where needed; unused `json`/`hashlib` top-level
  imports removed since their only remaining uses moved with the
  functions).
- Monkeypatch audit (ground rule 3):
  `git grep -n "_get_company_news_signature_payload\|
  _ensure_company_news_prefetched_payload\|_resolve_analyst_input_signature\|
  _get_prefetched_analyst_payload" tests/` shows exactly three
  monkeypatches, all of the same name, all class-attribute patches on
  `BacktestWorkflowAdapter`:
  `tests/test_workflow_adapter_smart_priority.py:723`
  (`test_shared_phase1_reuses_prefetched_company_news_payload_for_execution`),
  `:792`
  (`test_shared_analyst_cache_invalidates_company_news_on_input_signature_change`),
  and `:909`
  (`test_shared_phase1_artifact_news_change_invalidates`). No
  module-level bare-global patches exist for any of the eight names —
  the class-attribute delegator pattern (ground rule 3's second
  bullet) is sufficient, with the added discipline that internal calls
  between the eight functions route through the delegator rather than
  the module function directly (see design.md).
  Experimentally verified during implementation: temporarily changing
  `_ensure_company_news_prefetched_payload`'s internal call from
  `adapter._get_company_news_signature_payload(...)` to the bare module
  function `_get_company_news_signature_payload(adapter, ...)` made
  `test_shared_analyst_cache_invalidates_company_news_on_input_signature_change`
  fail (`{'company_news': 1} == {'company_news': 2}` assertion error);
  reverted before landing this change.
