## Context

`run.py` defines `_validate_environment`, `_print_backtest_env_error`,
`_configured_us_data_provider`, `_validate_non_llm_backtest_environment`,
and `_validate_backtest_environment_for_runtime` as one contiguous block,
plus `check_env_file` further down. `_validate_backtest_environment_for_runtime`
calls `_validate_environment(mode="backtest", verbose=verbose)` when
`runtime["use_llm"]` is true. `run_deepear`/`run_deepfund`/`main()` (all
staying in `run.py`) call `_validate_environment` and `check_env_file`
directly and are unaffected by this change.

`tests/test_backtest_fof_config_runtime.py:333-348` is the reproduction
case: it monkeypatches `run._validate_environment` with a call-recording
fake, then asserts `_validate_backtest_environment_for_runtime(runtime,
verbose=False)` both returns `True` *and* that the fake was called with
`("backtest", False)`. If the internal call resolved against
`runner.env_validation`'s own `_validate_environment` (the real
implementation, which would call the actual
`shared.config.validator.validate_env` and likely raise/return based on
real environment state, not the recorded fake), the assertion on `calls`
would fail — this is a hard failure, not a silent pass, precisely
because the test also asserts on the *fake's* side effect. (Ground rule
3 frames this class of bug as "silently stops testing the real path";
here the specific test used to prove the fix happens to fail loudly, but
the general risk — a moved caller's internal call missing a monkeypatch
— is the one ground rule 3 warns about, and it is the one this shim
exists to close for any future addition to this call chain.)

## Goals / Non-Goals

**Goals:** move all six functions; introduce `runner/_shim.py` in the
same commit; route the one internal monkeypatch-sensitive call through
it; add the subprocess smoke test that exercises the `__main__` fallback
branch; keep every `run.<name>` re-export and `from run import <name>`
import working.

**Non-Goals:** touching `run_deepear`, `run_deepfund`, `main()`, or any
other caller of these six functions (all stay in `run.py`, unaffected);
changing validation logic, error messages, or precedence.

## Decisions

1. **Shim shape matches the ticket's mandated implementation exactly:**
   `sys.modules.get("run")` if it has `_validate_environment`, else
   `sys.modules.get("__main__")`. The `hasattr` guard exists because
   `sys.modules.get("run")` could in principle resolve to an unrelated
   or partially-initialized module named "run" in some embedding
   scenario; checking for the specific attribute this shim exists to
   observe is a cheap sanity check before treating it as the real
   `run.py`.
2. **Only one call needs the shim.** `_validate_non_llm_backtest_environment`
   calls `_print_backtest_env_error` and `_configured_us_data_provider`,
   but both move in the same commit and neither is independently
   monkeypatched (grep confirmed), so their bare-name calls resolve
   correctly inside `runner.env_validation` with no indirection needed.
   Only `_validate_backtest_environment_for_runtime` -> `_validate_environment`
   crosses the "moved caller, independently-monkeypatched callee"
   boundary ground rule 3 warns about.
3. **Fallback order:** `getattr(_shim.run_module(), "_validate_environment",
   None) or _validate_environment`. `getattr` on `None` (when neither
   `sys.modules["run"]` nor `sys.modules["__main__"]` exists / exposes
   the attribute) safely returns the fallback default without a
   separate `is None` branch. This favors the module-resolved function
   when available (patched or the genuine re-export) and only falls
   back to the local definition when no `run`/`__main__` module context
   exists at all (e.g. `runner.env_validation` imported standalone in a
   unit test that never touches `run`).
4. **`check_env_file` substitutes `get_project_root()`** for the
   out-of-scope `PROJECT_ROOT` global — the same pattern used in
   `extract-run-config-discovery`, for the same reason (no monkeypatch
   coverage, byte-identical resolved value).
5. **Subprocess smoke test is mandatory, not optional**, per the ticket:
   `--check-env` is chosen because it's the fastest fully-deterministic
   path through `main()` that doesn't require API keys or network
   access, and it is the one CLI flag guaranteed to short-circuit before
   any mode dispatch.

## Risks / Trade-offs

- The subprocess smoke test spawns a real Python process (~1-2s
  overhead) — acceptable for a one-off environment check, and it is the
  only test in the suite that reaches the `__main__` fallback branch of
  the shim.
- `runner/_shim.py`'s `hasattr` check is a heuristic, not a guarantee —
  if `run.py` is ever renamed such that `_validate_environment` stops
  being one of its top-level re-exports, the shim would silently fall
  through to `__main__`. Acceptable: the shim's job is to survive the
  specific decomposition in progress, not arbitrary future renames.
