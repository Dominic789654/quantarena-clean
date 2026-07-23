## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "monkeypatch.setattr" tests/ | grep "run\."` --
  full inventory (see proposal.md) of every `run.*` string patch
  touching a name in scope for this change:
  `_print_backtest_result` (:231,259,443), `run_backtest_mode` (:55),
  `_validate_backtest_environment_for_runtime` (:232,260,372,444),
  `_validate_backtest_date_range` (:371,736),
  `_print_multi_personality_results` (:737).
- [x] 1.2 Classify each by caller: `_print_backtest_result` and (at
  :232,260,444) `_validate_backtest_environment_for_runtime` are
  patched while calling `_execute_backtest_mode` directly --
  **shim in `_execute_backtest_mode`**.
  `_validate_backtest_date_range` and (at :372) `
  _validate_backtest_environment_for_runtime` and
  `_print_multi_personality_results` are patched while calling
  `run_multi_personality_mode` directly -- **shim in
  `run_multi_personality_mode`**. `run_backtest_mode` is patched while
  calling `main()` -- caller stays in `run.py` this change, **no shim
  yet** (deferred to step 8).
- [x] 1.3 Per design.md decision 2, also shim
  `_execute_backtest_mode`'s call to `_validate_backtest_date_range`
  even though no test patches it via that specific call path --
  the function itself is on the monkeypatch-sensitive list.

## 2. Implementation

- [x] 2.1 Add `runner/modes/backtest.py` with `_validate_backtest_date_range`,
  `_execute_backtest_mode` (with `_shim`-routed calls to
  `_validate_backtest_date_range`, `_validate_backtest_environment_for_runtime`,
  `_print_backtest_result`), and `run_backtest_mode`, moved verbatim.
- [x] 2.2 Add `runner/modes/multi_personality.py` with
  `run_multi_personality_mode` (with `_shim`-routed calls to
  `_validate_backtest_date_range` (imported from
  `runner.modes.backtest`), `_validate_backtest_environment_for_runtime`,
  `_print_multi_personality_results`), moved verbatim.
- [x] 2.3 `run.py`: replace the four definitions with
  `from runner.modes.backtest import (...)` and
  `from runner.modes.multi_personality import run_multi_personality_mode`
  (each `# noqa: F401`).
- [x] 2.4 Drop `run.py`'s now-unused `from datetime import datetime`
  and `from typing import Optional, Any` (only referenced by the moved
  functions' bodies/type hints).
- [x] 2.5 Keep the pre-existing `runner.cli_support`/`runner.runtime_options`
  re-export import lines for `_print_backtest_mode_config`/
  `_print_backtest_result`/`_print_multi_personality_config`/
  `_print_multi_personality_results` in `run.py` unchanged (they were
  already re-exports as of `extract-run-cli-support-helpers`; this
  change does not touch them beyond keeping them in place).

## 3. Verification

- [x] 3.1 Experimentally confirmed a shim is load-bearing: temporarily
  reverted `run_multi_personality_mode`'s
  `_validate_backtest_environment_for_runtime` call to bypass `_shim`
  and re-ran `test_run_multi_personality_mode_validates_after_runtime_resolution`
  in isolation -- it failed (`AttributeError: 'NoneType' object has no
  attribute 'run_id'`). Restored the shim; re-ran -- passed.
- [x] 3.2 `.venv_unified/bin/python -m pytest tests/ -q` -- 935 passed
  (baseline unchanged; no new tests in this change), 10 skipped, 0
  failed.
- [x] 3.3 `.venv_unified/bin/ruff check .` clean.
- [x] 3.4 `python run.py --check-env` exits 0.
