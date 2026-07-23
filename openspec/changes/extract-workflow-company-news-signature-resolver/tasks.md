## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "_get_company_news_signature_payload\|
  _ensure_company_news_prefetched_payload\|_resolve_analyst_input_signature\|
  _get_prefetched_analyst_payload" tests/` — exactly three
  monkeypatches, all class-attribute patches of the same name on
  `BacktestWorkflowAdapter`, all in
  `tests/test_workflow_adapter_smart_priority.py` (lines 723, 792,
  909). No monkeypatch of `_stable_json_signature`,
  `_normalize_news_item`, `_build_phase1_prefetched_analyst_inputs`, or
  `_resolve_phase1_input_metadata` exists anywhere in `tests/`.
- [x] 1.2 Confirm the three patched tests exercise the patch through
  multiple internal-call hops (not just a direct call to the patched
  method): `test_shared_phase1_reuses_prefetched_company_news_payload_
  for_execution` goes through `load_or_compute_shared_phase1` ->
  `_build_phase1_prefetched_analyst_inputs`; `test_shared_analyst_cache_
  invalidates_company_news_on_input_signature_change` goes through
  `_process_single_ticker_for_signals_v2` ->
  `_resolve_analyst_input_signature` ->
  `_ensure_company_news_prefetched_payload`; `test_shared_phase1_
  artifact_news_change_invalidates` goes through
  `load_or_compute_shared_phase1` -> `_resolve_phase1_input_metadata` ->
  `_ensure_company_news_prefetched_payload`.

## 2. Implementation

- [x] 2.1 Add `backtest/workflow/company_news_signature.py` with the
  eight functions. `_stable_json_signature`, `_normalize_news_item`,
  `_get_prefetched_analyst_payload` keep their original no-adapter
  signatures (moved verbatim). `_get_company_news_signature_payload`,
  `_ensure_company_news_prefetched_payload`,
  `_build_phase1_prefetched_analyst_inputs`,
  `_resolve_analyst_input_signature`, `_resolve_phase1_input_metadata`
  take `adapter` as their first parameter, replacing `self`; every
  internal call between the eight functions goes through
  `adapter.<name>(...)`.
- [x] 2.2 `backtest/workflow_adapter.py`: replace the eight method
  bodies with delegators — `staticmethod(company_news_signature.<name>)`
  direct assignment for the three pure helpers, `def` instance methods
  calling `company_news_signature.<name>(self, ...)` for the five that
  need adapter state. Remove the now-unused top-level `json`/`hashlib`
  imports (their only remaining uses moved with the functions).
- [x] 2.3 Experimentally verify the patch-propagation discipline: with
  the codebase in its post-move state, temporarily change
  `_ensure_company_news_prefetched_payload`'s internal call from
  `adapter._get_company_news_signature_payload(...)` to a bare
  `company_news_signature._get_company_news_signature_payload(adapter,
  ...)` module call; confirm
  `test_shared_analyst_cache_invalidates_company_news_on_input_signature_change`
  fails; revert.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest
  tests/test_workflow_adapter_smart_priority.py -q` — all 14 tests
  pass (both before and after step 2.3's revert).
- [x] 3.2 `.venv_unified/bin/python -m pytest tests/ -q` — baseline +
  0 new tests (this change adds no tests), 0 failed.
- [x] 3.3 `.venv_unified/bin/ruff check .` clean.
