## Context

`backtest/workflow_adapter.py`'s eight signature-resolver methods
(~lines 571-717 at the start of this change) sit between two caches:
the per-(ticker, analyst, llm) `SharedAnalystSignalCache` (a file cache,
`backtest/workflow/signal_cache.py`) and the per-trading-day
`SharedPhase1ArtifactCache` (`backtest/workflow/phase1_artifact.py`).
Both need to know whether a ticker's `company_news` analyst input has
changed since the cache entry was written, because the news feed for a
given `(ticker, trading_date)` can differ between two runs (new articles
published, upstream API returning a different page). The resolver chain
computes a signature over the fetched news items and threads it through
`_process_single_ticker_for_signals_v2` (per-ticker signal collection,
still in `workflow_adapter.py`, extracted in a later Phase-3 step) and
`load_or_compute_shared_phase1` (still in `workflow_adapter.py`) so both
caches key on it.

Three of the eight methods read instance state:
`_get_company_news_signature_payload` reads `self.market` and
`self.api_source` (needed to build the `Router`);
`_build_phase1_prefetched_analyst_inputs` and
`_resolve_phase1_input_metadata` read `self.analysts` (needed to check
whether `"company_news"` is an active analyst before doing any news
fetching at all).

## Goals / Non-Goals

**Goals:** move all eight functions into
`backtest/workflow/company_news_signature.py` with parameter-lifting
only where instance state is read; keep every `self.<name>(...)` call
site working via same-named delegators; preserve the
`_get_company_news_signature_payload` class-attribute monkeypatch's
reach into every internal caller.

**Non-Goals:** changing the signature algorithm itself (still SHA1 of a
sorted-keys JSON dump, truncated to 12 hex chars); changing which
analyst key triggers signature resolution (still only `"company_news"`,
by design — the other two default analysts, `fundamental` and
`technical`, do not have an input-signature-based cache-invalidation
path today; out of scope for this change).

## Decisions

1. **Adapter-passing over attribute-lifting.** The plan text explicitly
   leaves this as an implementer's call ("needs self.market/self.api_
   source/self.analysts — lift params or pass the adapter explicitly,
   your call, justify"). This change passes the adapter instance as an
   explicit `adapter` parameter (mirroring the original `self`
   receiver) rather than lifting `market`, `api_source`, and `analysts`
   into three separate positional parameters, for two reasons:
   - **Patch propagation.** `_get_company_news_signature_payload` is
     monkeypatched as a *class attribute* in three tests. If the
     internal callers (`_ensure_company_news_prefetched_payload`,
     `_build_phase1_prefetched_analyst_inputs`,
     `_resolve_phase1_input_metadata` via
     `_ensure_company_news_prefetched_payload`) called a bare module
     function instead of going through the adapter, the class-attribute
     patch would only affect *direct* callers of the delegator, not
     these internal hops — silently breaking the very cache-invalidation
     behavior these tests exist to verify. Passing `adapter` and calling
     `adapter._get_company_news_signature_payload(...)` from inside the
     module keeps the patch's reach identical to before the move.
   - **Call-site stability.** Three-parameter lifting (`market`,
     `api_source`, `analysts`) would force every call site — including
     `_process_single_ticker_for_signals_v2`'s call to
     `_resolve_analyst_input_signature`, which is *not* being moved in
     this change (it stays in `workflow_adapter.py` until the
     `extract-workflow-signal-collection-engine` step) — to be updated
     with three new arguments it does not currently pass. Passing
     `adapter` means that unmoved call site's `self._resolve_analyst_
     input_signature(trading_date, ticker, analyst_key,
     prefetched_analyst_data)` call is untouched; only the
     *delegator body* changes.
2. **Three pure helpers keep their original no-adapter signatures.**
   `_stable_json_signature`, `_normalize_news_item`, and
   `_get_prefetched_analyst_payload` never read `self`/instance state
   in the original (all three were already `@staticmethod`s); they move
   verbatim with no signature change, and the class keeps them as
   direct `staticmethod(company_news_signature.<name>)` attribute
   assignments (the pattern already used for `_signal_label` /
   `_aggregate_signal_from_summary` in `backtest/workflow/scoring.py`'s
   delegators, and for `_normalize_decision_for_portfolio` /
   `_update_portfolio_ticker` in `decision_apply.py`'s).
3. **All internal calls route through the delegator, uniformly, even
   for the three pure helpers that are never patched today.** This is
   stricter than strictly necessary (only
   `_get_company_news_signature_payload` is patched by any test today),
   but matches the task's explicit instruction and defends against a
   future test patching any of the other seven the same way — the cost
   is zero (one extra attribute lookup per call, already true of every
   other delegator in this codebase) and the benefit is that this
   module's patchability story is uniform rather than
   name-by-name-dependent.

## Risks / Trade-offs

- Passing the whole adapter instance instead of three named parameters
  is slightly less explicit about exactly which attributes each
  function reads — mitigated by each function's own short body making
  the reads obvious (`adapter.market`, `adapter.api_source`,
  `adapter.analysts`), and by this design doc calling them out.
- No behavior change; risk is purely "did the patch-propagation survive
  the move", closed by the experimental verification recorded in
  proposal.md's Impact section and by the full test suite run.
