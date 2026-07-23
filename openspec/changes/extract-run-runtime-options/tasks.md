## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "monkeypatch" tests/ | grep -E
  "_resolve_backtest_runtime_options|_resolve_multi_personality_runtime_options|_extract_market_from_config|_extract_tickers_from_config|_parse_tickers_arg|_parse_optional_csv|_parse_personalities_arg|DEFAULT_BACKTEST_ANALYSTS_ARG|VALID_PERSONALITIES"`
  — no hits.
- [x] 1.2 `git grep -n "_parse_personalities_arg\|DEFAULT_BACKTEST_ANALYSTS_ARG\|VALID_PERSONALITIES" run.py`
  to confirm every internal caller of these names before the move, and
  that each caller is itself in scope for this change (or, for the two
  constants, that the referencing functions are moving).

## 2. Implementation

- [x] 2.1 Add `runner/runtime_options.py` with `DEFAULT_BACKTEST_ANALYSTS_ARG`,
  `VALID_PERSONALITIES`, `_extract_market_from_config`,
  `_extract_tickers_from_config`, `_parse_tickers_arg`,
  `_parse_optional_csv`, `_parse_personalities_arg`,
  `_resolve_backtest_runtime_options`,
  `_resolve_multi_personality_runtime_options`, importing
  `_load_yaml_config_file`/`_select_backtest_config_file` from
  `runner.config_discovery` and `VALID_PROFILE_NAMES` from
  `shared.config.profile_registry`.
- [x] 2.2 `run.py`: replace `DEFAULT_BACKTEST_ANALYSTS_ARG = "..."` with
  `from runner.runtime_options import DEFAULT_BACKTEST_ANALYSTS_ARG  #
  noqa: F401`.
- [x] 2.3 `run.py`: replace the `_extract_market_from_config` /
  `_extract_tickers_from_config` / `_resolve_backtest_runtime_options` /
  `_resolve_multi_personality_runtime_options` definitions with one
  `from runner.runtime_options import (...)  # noqa: F401` block.
- [x] 2.4 `run.py`: replace `VALID_PERSONALITIES = list(VALID_PROFILE_NAMES)`
  + `_parse_tickers_arg` def with
  `from runner.runtime_options import VALID_PERSONALITIES,
  _parse_tickers_arg  # noqa: F401`.
- [x] 2.5 `run.py`: replace `_parse_optional_csv` def with
  `from runner.runtime_options import _parse_optional_csv  # noqa:
  F401`.
- [x] 2.6 `run.py`: replace `_parse_personalities_arg` def with
  `from runner.runtime_options import _parse_personalities_arg  # noqa:
  F401`.
- [x] 2.7 Drop `run.py`'s now-unused `from shared.config.profile_registry
  import VALID_PROFILE_NAMES` (only consumer, `VALID_PERSONALITIES`,
  moved).

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` — 928 passed, 10
  skipped, 0 failed.
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
- [x] 3.3 `python run.py --check-env` exits 0.
