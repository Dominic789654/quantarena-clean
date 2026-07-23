## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "monkeypatch" tests/ | grep -E
  "print_banner|_print_backtest_mode_config|_print_backtest_result|_print_multi_personality_config|_print_multi_personality_results"`
  -- `run._print_backtest_result` patched at
  `test_backtest_fof_config_runtime.py:231,259,443`; `run.print_banner`
  patched at `:56`. Both callers (`_execute_backtest_mode`, `main()`)
  stay in `run.py` in this change -- no `_shim` needed yet.
- [x] 1.2 Confirm `_print_backtest_mode_config`,
  `_print_multi_personality_config`, `_print_multi_personality_results`
  have zero monkeypatch coverage.

## 2. Implementation

- [x] 2.1 Add `runner/cli_support.py` with the five functions moved
  verbatim.
- [x] 2.2 `run.py`: replace `print_banner`'s definition with
  `from runner.cli_support import print_banner  # noqa: F401`.
- [x] 2.3 `run.py`: replace the `_print_backtest_mode_config` /
  `_print_backtest_result` definitions with one
  `from runner.cli_support import (...)  # noqa: F401` block.
- [x] 2.4 `run.py`: replace the `_print_multi_personality_config` /
  `_print_multi_personality_results` definitions with one
  `from runner.cli_support import (...)  # noqa: F401` block.
- [x] 2.5 Drop `run.py`'s now-unused `Dict`/`List` typing imports.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` -- 929 passed,
  10 skipped, 0 failed (baseline unchanged; no new tests in this
  change).
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
- [x] 3.3 `python run.py --check-env` exits 0.
