## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "monkeypatch" tests/ | grep -E
  "_get_deepfund_config_candidates|_load_yaml_config_file|_select_backtest_config_file"`
  — no hits. `git grep -n "from run import\|import run\b" tests/` —
  `test_run_config_selection.py` and `test_backtest_fof_config_runtime.py`
  import these names directly (plain imports, not monkeypatches).

## 2. Implementation

- [x] 2.1 Add `runner/config_discovery.py` with
  `_get_deepfund_config_candidates`, `_load_yaml_config_file`,
  `_select_backtest_config_file` moved from `run.py`, substituting
  `get_project_root()` for the no-longer-in-scope `PROJECT_ROOT` global
  in the first and third functions.
- [x] 2.2 `run.py`: replace the three definitions with
  `from runner.config_discovery import _get_deepfund_config_candidates,
  _load_yaml_config_file, _select_backtest_config_file  # noqa: F401`.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` — 928 passed, 10
  skipped, 0 failed.
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
- [x] 3.3 `python run.py --check-env` exits 0.
