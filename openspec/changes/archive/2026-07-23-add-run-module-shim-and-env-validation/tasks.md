## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "monkeypatch" tests/ | grep -E
  "_validate_environment|_validate_non_llm_backtest_environment|_validate_backtest_environment_for_runtime|check_env_file"`
  — `run._validate_environment` patched at
  `test_backtest_fof_config_runtime.py:345,735`;
  `run._validate_backtest_environment_for_runtime` patched at
  `:232,260,372,444` (patches the caller directly, not affected by the
  internal-call trap).
- [x] 1.2 Confirm the trap: `_validate_backtest_environment_for_runtime`
  calls `_validate_environment` internally
  (`test_llm_backtest_validation_uses_full_env_validator`, ~line
  333-348, is the reproduction case named in ground rule 3).
- [x] 1.3 Confirm `_print_backtest_env_error` /
  `_configured_us_data_provider` have zero independent monkeypatch
  coverage — no shim needed for those internal calls.

## 2. Implementation

- [x] 2.1 Add `runner/_shim.py` with `run_module()` exactly as specified
  (`sys.modules.get("run")` if it has `_validate_environment`, else
  `sys.modules.get("__main__")`).
- [x] 2.2 Add `runner/env_validation.py` with the six functions moved
  verbatim, routing `_validate_backtest_environment_for_runtime`'s
  internal `_validate_environment` call through
  `_shim.run_module()` with a fallback to the local function, and
  `check_env_file` resolving the project root via `get_project_root()`.
- [x] 2.3 `run.py`: replace the six definitions with
  `from runner.env_validation import (...)  # noqa: F401`.
- [x] 2.4 Drop `run.py`'s now-unused `from shared.config.provider_routing
  import preferred_us_data_provider`, `import os`, `from pathlib import
  Path` (all only referenced by the moved functions).
- [x] 2.5 Add `tests/test_run_subprocess_smoke.py`:
  `subprocess.run([sys.executable, "run.py", "--check-env"], cwd=project_root, ...)`
  asserting exit 0.

## 3. Verification

- [x] 3.1 Experimentally confirmed the shim is load-bearing: temporarily
  reverted `_validate_backtest_environment_for_runtime` to call
  `_validate_environment` directly (bypassing `_shim`) and re-ran
  `test_llm_backtest_validation_uses_full_env_validator` in isolation —
  it failed (`assert False is True`). Restored the shim; re-ran — passed.
- [x] 3.2 `.venv_unified/bin/python -m pytest tests/ -q` — 929 passed
  (928 baseline + 1 new subprocess smoke test), 10 skipped, 0 failed.
- [x] 3.3 `.venv_unified/bin/ruff check .` clean.
- [x] 3.4 `python run.py --check-env` exits 0.
