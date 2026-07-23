## Why

This is the critical step of the run.py decomposition
(docs/refactor_program_plan.md Phase 2, step 4 of 8, "the critical
step"). `_validate_environment`, `_validate_non_llm_backtest_environment`,
`_validate_backtest_environment_for_runtime`, and `check_env_file` are
the last helpers standing between run.py and its mode handlers. Unlike
every helper moved so far,
`_validate_backtest_environment_for_runtime` calls `_validate_environment`
internally, and `tests/test_backtest_fof_config_runtime.py::test_llm_backtest_validation_uses_full_env_validator`
(~line 345, pre-existing) monkeypatches `run._validate_environment` and
expects that internal call to observe the patch. Moving both functions
into the same `runner/` module without addressing this breaks that test
silently (it keeps passing but stops exercising the patched path) unless
the internal call is routed back through the public `run` module. This
change also has zero real "exec run.py as a script" coverage today —
every existing test imports functions directly and monkeypatches them.

## What Changes

- Add `runner/env_validation.py` holding, moved verbatim from `run.py`:
  `_validate_environment`, `_print_backtest_env_error`,
  `_configured_us_data_provider`, `_validate_non_llm_backtest_environment`,
  `_validate_backtest_environment_for_runtime`, `check_env_file`.
- Add `runner/_shim.py` with `run_module()`
  (`sys.modules.get("run")` if it exposes `_validate_environment`, else
  `sys.modules.get("__main__")`) — required in the **same commit** per
  ground rule 3.
- `_validate_backtest_environment_for_runtime`'s internal call to
  `_validate_environment` is routed through
  `_shim.run_module()`, falling back to the local
  `_validate_environment` when the shim finds no usable module (e.g.
  this module used standalone, outside run.py).
- `check_env_file` resolves the project root via `get_project_root()`
  instead of run.py's now-out-of-scope `PROJECT_ROOT` global (same
  substitution pattern as `extract-run-config-discovery`).
- `run.py` re-exports all six names from `runner.env_validation`.
- Add `tests/test_run_subprocess_smoke.py`: a real
  `subprocess.run([sys.executable, "run.py", "--check-env"], ...)`
  asserting exit 0 — exercises the `__main__`-registration path the
  shim's fallback branch depends on, which no existing test reaches.

## Capabilities

### New Capabilities
- `run-env-validation`: environment-variable and backtest-data-dependency
  validation used by every run.py mode (deepear, deepfund, backtest,
  multi-personality) plus the `.env`-file bootstrap check.
- `run-module-shim`: the `sys.modules`-based indirection that lets code
  living in `runner/` observe monkeypatches applied to the public `run`
  module (or `__main__`, when run.py executes as a script) for functions
  it calls internally.

### Modified Capabilities
- None.

## Impact

- `run.py`, new `runner/env_validation.py`, new `runner/_shim.py`, new
  `tests/test_run_subprocess_smoke.py`.
- Monkeypatch audit (ground rule 3):
  `git grep -n "monkeypatch" tests/ | grep -E
  "_validate_environment|_validate_non_llm_backtest_environment|_validate_backtest_environment_for_runtime|check_env_file"`
  finds `run._validate_environment` patched at
  `test_backtest_fof_config_runtime.py:345,735` and
  `run._validate_backtest_environment_for_runtime` patched at
  `:232,260,372,444` (the latter patches the caller itself, not an
  internal call — unaffected by the move). Line 345/347's test
  (`test_llm_backtest_validation_uses_full_env_validator`) is the
  reproduction case ground rule 3 calls out by name: it calls
  `_validate_backtest_environment_for_runtime` directly while the patch
  sits on `run._validate_environment`, and only the `_shim` indirection
  keeps that patch observed once both functions live in
  `runner.env_validation`. Verified experimentally during this change:
  temporarily reverting the shim to a bare `_validate_environment(...)`
  call reproduces the exact silent-pass failure mode (the test fails
  with `assert False is True`, proving the fix is load-bearing), then
  the shim was restored.
- `_print_backtest_env_error` and `_configured_us_data_provider` are
  called only by `_validate_non_llm_backtest_environment`, which moves
  in the same commit — no shim needed for that pair (same-module
  bare-name resolution after the move).
- `check_env_file`'s only caller, `main()`, stays in `run.py`
  unchanged and calls it by its re-exported bare name.
