## Why

Continuing the run.py decomposition (docs/refactor_program_plan.md Phase
2, step 7 of 8): `_validate_backtest_date_range`, `_execute_backtest_mode`,
`run_backtest_mode`, and `run_multi_personality_mode` are the last mode
handlers in run.py. Unlike steps 5-6, this group has the highest
monkeypatch density in the whole file:
`tests/test_backtest_fof_config_runtime.py` patches
`run._print_backtest_result`, `run._validate_backtest_environment_for_runtime`,
`run._validate_backtest_date_range`, and
`run._print_multi_personality_results` while calling
`_execute_backtest_mode`/`run_multi_personality_mode` directly. All four
callees now live in other `runner/` modules moved by earlier changes
(`runner.env_validation`, `runner.cli_support`) or in this change's own
new sibling module (`_validate_backtest_date_range`, shared between the
two mode handlers). Once the callers themselves leave `run.py`'s
namespace, their bare-name calls to these four functions stop observing
patches applied to `run.py`'s re-exports unless routed through
`runner/_shim.py`.

## What Changes

- Add `runner/modes/backtest.py` holding, moved verbatim from `run.py`:
  `_validate_backtest_date_range`, `_execute_backtest_mode`,
  `run_backtest_mode`.
- Add `runner/modes/multi_personality.py` holding, moved verbatim from
  `run.py`: `run_multi_personality_mode` (importing
  `_validate_backtest_date_range` from the sibling `runner.modes.backtest`).
- `_execute_backtest_mode`'s calls to `_validate_backtest_date_range`,
  `_validate_backtest_environment_for_runtime`, and
  `_print_backtest_result` are routed through `runner._shim.run_module()`.
- `run_multi_personality_mode`'s calls to `_validate_backtest_date_range`,
  `_validate_backtest_environment_for_runtime`, and
  `_print_multi_personality_results` are routed through
  `runner._shim.run_module()`.
- `run.py` re-exports `_validate_backtest_date_range`,
  `_execute_backtest_mode`, `run_backtest_mode`, and
  `run_multi_personality_mode` from the two new modules.
- No behavior change: identical validation/config-resolution/printing
  logic and ordering.

## Capabilities

### New Capabilities
- `run-backtest-multipersonality-modes`: the backtest and
  multi-personality CLI mode handlers, including the monkeypatch-safe
  `_shim` routing for every internal call whose callee is independently
  patched via a `run.*` string path anywhere in the test suite.

### Modified Capabilities
- None.

## Impact

- `run.py`, new `runner/modes/backtest.py`, new
  `runner/modes/multi_personality.py`.
- Monkeypatch audit (ground rule 3), full inventory from
  `git grep -n "monkeypatch.setattr" tests/ | grep -E "run\\."` restricted
  to names in scope for this change:
  - `run._print_backtest_result` -- patched at
    `test_backtest_fof_config_runtime.py:231,259,443`, all while calling
    `_execute_backtest_mode` directly. **Shimmed** in
    `_execute_backtest_mode`.
  - `run._validate_backtest_environment_for_runtime` -- patched at
    `:232,260,372,444`. Lines 232/260/444 patch it while calling
    `_execute_backtest_mode` directly (**shimmed** there); line 372
    patches it while calling `run_multi_personality_mode` (**shimmed**
    there too).
  - `run._validate_backtest_date_range` -- patched at `:371,736`, both
    while calling `run_multi_personality_mode` directly. **Shimmed** in
    `run_multi_personality_mode`. Because the patch-sensitivity attaches
    to the function itself (not to one specific caller), the *other*
    caller of the same function, `_execute_backtest_mode`, is shimmed
    too, for consistency and to close the same latent gap even though
    no test currently exercises that exact call path with the patch
    applied -- see design.md decision 2 for why this is the correct
    reading of "wherever the callee is patched on run.*".
  - `run._print_multi_personality_results` -- patched at `:737`, while
    calling `run_multi_personality_mode`. **Shimmed** there.
  - `run.run_backtest_mode` -- patched at `:55`, while calling
    `run.main()`. `main()` stays in `run.py` in this change (out of
    scope until step 8), so its bare-name call to `run_backtest_mode`
    still resolves against `run.py`'s own re-exported global -- no shim
    needed yet. This is exactly the call site step 8 will need to shim.
  - `_print_backtest_mode_config`, `_print_multi_personality_config`,
    `_resolve_backtest_runtime_options`,
    `_resolve_multi_personality_runtime_options` -- zero monkeypatch
    coverage; their calls stay plain bare-name calls.
- Experimentally verified two of the four shim routings are
  load-bearing: temporarily reverted
  `run_multi_personality_mode`'s `_validate_backtest_environment_for_runtime`
  call to a bare call (bypassing `_shim`) and re-ran
  `test_run_multi_personality_mode_validates_after_runtime_resolution`
  in isolation -- it failed with `AttributeError: 'NoneType' object has
  no attribute 'run_id'` (the real, unpatched validator let a `None`
  comparison flow downstream instead of the test's fake short-circuit).
  Restored the shim; re-ran -- passed. (The `_validate_backtest_date_range`
  shim in the same function was *not* independently reproducible this
  way: both tests that patch it use CLI-valid default dates, so the
  real validator happens to agree with the patch's return value for
  those specific inputs -- the shim is still correct per the audit rule
  above, just not empirically distinguishable with the existing test
  fixtures.)
