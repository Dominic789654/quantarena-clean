## Context

Post `extract-run-mode-handlers-deepear-deepfund-pipeline`, `run.py`'s
only remaining functions are `_validate_backtest_date_range`,
`_execute_backtest_mode`, `run_backtest_mode`,
`run_multi_personality_mode`, and `main`. `_validate_backtest_date_range`
is a private helper shared by the first three and by
`run_multi_personality_mode`. `_execute_backtest_mode` calls
`_validate_backtest_date_range`, `_resolve_backtest_runtime_options`,
`_validate_backtest_environment_for_runtime`,
`_print_backtest_mode_config`, and `_print_backtest_result`.
`run_multi_personality_mode` calls the same shape of functions for the
multi-personality path. `run_backtest_mode` calls `_execute_backtest_mode`.
`main()` (out of scope, step 8) calls `run_backtest_mode` and
`run_multi_personality_mode` by bare name.

`tests/test_backtest_fof_config_runtime.py` is unusually dense: several
tests import `_execute_backtest_mode` and `run_multi_personality_mode`
directly from `run` and monkeypatch four of their transitive callees
via `run.<name>` string paths, expecting the direct call (not routed
through `main()`) to observe the patch.

## Goals / Non-Goals

**Goals:** move all four functions; identify every internal call whose
callee is monkeypatched via `run.*` anywhere in the suite and route it
through `runner._shim.run_module()`; keep every `run.<name>` re-export
and `from run import <name>` import working; experimentally prove at
least one shim is load-bearing.

**Non-Goals:** touching `main()` (step 8, which will need to shim its
own calls to `run_backtest_mode`/`run_multi_personality_mode`/
`print_banner` once it too leaves `run.py`).

## Decisions

1. **Two files: `runner/modes/backtest.py` and
   `runner/modes/multi_personality.py`.** The ticket allowed either
   shape. Splitting was chosen for the same reason as
   `extract-run-mode-handlers-deepear-deepfund-pipeline`'s deepear/
   deepfund/pipeline split: `run_multi_personality_mode` pulls in
   `backtest.multi_personality_engine` (a distinct, heavier subsystem
   from `backtest.engine`), and keeping it separate means importing
   `runner.modes.backtest` alone never pulls in the multi-personality
   engine's import surface. `_validate_backtest_date_range` -- used by
   both -- lives in `backtest.py` (it was defined first in `run.py`'s
   source order, ahead of `_execute_backtest_mode`) and
   `multi_personality.py` imports it from there, rather than
   duplicating the function or introducing a third shared-helpers
   module for one four-line function.
2. **Shim scope: "wherever the callee is patched on run.*" means every
   caller of that callee, not just the one call site a test happens to
   exercise.** `_validate_backtest_date_range` is monkeypatched via
   `run.*` only in the context of `run_multi_personality_mode` calls
   (lines 371, 736) -- no test patches it while calling
   `_execute_backtest_mode` directly. It would be tempting to shim only
   the tested call site (as `add-run-module-shim-and-env-validation`'s
   design.md did for `_print_backtest_env_error`/
   `_configured_us_data_provider`, which had *zero* monkeypatch
   coverage at all). But that precedent's reasoning doesn't transfer:
   those two functions were never independently patched by any test,
   anywhere. `_validate_backtest_date_range` *is* independently
   patched, just via a different caller. The risk ground rule 3
   describes -- a caller silently stops observing a patch once it
   leaves the callee's original defining module -- applies identically
   to `_execute_backtest_mode`'s call, whether or not a test currently
   happens to probe it. Both calls are shimmed. (This decision was
   validated empirically: see the "not independently reproducible"
   note in proposal.md -- the *test evidence* for
   `_execute_backtest_mode`'s copy doesn't exist today, but the
   *structural risk* does, and closing it now is strictly cheaper than
   waiting for a future test to hit it.)
3. **`_print_backtest_mode_config`/`_print_multi_personality_config`/
   both `_resolve_*_runtime_options` stay bare-name calls.** Zero
   `run.*` monkeypatch coverage on any of the four (grep confirmed),
   so no shim indirection is warranted -- adding one would be pure
   ceremony with no test ever exercising the fallback branch.
4. **`run.run_backtest_mode`'s monkeypatch (line 55) is not shimmed in
   this change.** It's observed by `main()`, which calls
   `run_backtest_mode` by bare name -- and `main()` stays in `run.py`
   through this change, so the bare-name call still resolves against
   `run.py`'s own re-exported global. This is deliberately deferred to
   `extract-run-cli-entrypoint-package` (step 8), which is the change
   that moves `main()` itself out of `run.py` and must shim this call
   (along with `main()`'s calls to `print_banner`,
   `run_deepear`/`run_deepfund`/`run_full_pipeline`, and
   `run_multi_personality_mode`, per the same rule).
5. **Shim call shape matches the established
   `runner/env_validation.py` idiom exactly**: `getattr(_shim.run_module(),
   "<name>", None) or <local import>`, assigned to a local variable
   immediately before the guarded call, with a one-line comment citing
   the specific monkeypatch string path it protects.

## Risks / Trade-offs

- `multi_personality.py` importing `_validate_backtest_date_range` from
  `backtest.py` creates an intra-package dependency between the two new
  mode-handler modules where none existed at the `run.py` single-file
  level. Accepted: it mirrors the original single-namespace sharing
  exactly, and the alternative (duplicating the function or adding a
  third module for it) would either violate the verbatim-move
  constraint or add ceremony for a four-line helper.
- The `_validate_backtest_date_range` shim in `_execute_backtest_mode`
  is unverified by any existing test (see decision 2) -- accepted as a
  structural-consistency call, not a regression risk, since the shim
  is a strict superset of the bare call's behavior when no patch is
  active (`getattr(..., None) or <fallback>` degrades to the fallback).
