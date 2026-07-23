# run-runtime-options Specification

## Purpose
TBD - created by archiving change extract-run-runtime-options. Update Purpose after archive.
## Requirements
### Requirement: Backtest runtime option resolution precedence
`runner.runtime_options._resolve_backtest_runtime_options` SHALL resolve tickers, analysts, personality, market, cashflow, use_llm, and benchmark settings with the precedence explicit CLI flag (or non-default CLI value) over YAML config file value over hardcoded default, and SHALL raise `ValueError` when no tickers are resolved from either CLI args or the config file.

#### Scenario: Config file tickers used when CLI omits --tickers
- **WHEN** `args.tickers` is unset and the selected config file defines `tickers`
- **THEN** the resolved `tickers` list comes from the config file

#### Scenario: Missing tickers raises ValueError
- **WHEN** neither `args.tickers` nor the config file provide tickers
- **THEN** `_resolve_backtest_runtime_options` raises `ValueError("tickers are required for backtest mode")`

#### Scenario: use_llm inferred from config when not explicitly requested
- **WHEN** `args.use_llm` is `False` but the config sets `llm: true`, provides `workflow_analysts`, or `personality` resolves to `"fof"`
- **THEN** the resolved `use_llm` is `True`

### Requirement: Multi-personality runtime option resolution
`runner.runtime_options._resolve_multi_personality_runtime_options` SHALL resolve the same tickers/analysts/market/cashflow/benchmark precedence as the backtest resolver, SHALL always resolve `use_llm` to `True`, and SHALL raise `ValueError` when personalities fail validation against `VALID_PERSONALITIES`.

#### Scenario: Invalid personality raises ValueError
- **WHEN** `args.personalities` contains a value not in `VALID_PERSONALITIES`
- **THEN** `_resolve_multi_personality_runtime_options` raises `ValueError("invalid personalities for multi-personality mode")`

### Requirement: run.py re-exports runtime option resolvers and constants
`run.py` SHALL expose `_resolve_backtest_runtime_options`, `_resolve_multi_personality_runtime_options`, `_extract_market_from_config`, `_extract_tickers_from_config`, `_parse_tickers_arg`, `_parse_optional_csv`, `_parse_personalities_arg`, `DEFAULT_BACKTEST_ANALYSTS_ARG`, and `VALID_PERSONALITIES` as module attributes re-exported from `runner.runtime_options`, so existing `from run import ...` imports and `run.py`'s own unmoved `main()` argparse setup continue to resolve.

#### Scenario: Existing test imports keep working
- **WHEN** `tests/test_run_config_selection.py` runs `from run import (DEFAULT_BACKTEST_ANALYSTS_ARG, DEFAULT_MULTI_PERSONALITIES_ARG, _execute_backtest_mode, main, _validate_backtest_environment_for_runtime, _resolve_backtest_runtime_options, _resolve_multi_personality_runtime_options, _select_backtest_config_file, run_multi_personality_mode)`
- **THEN** every name resolves, with the runtime-option names backed by `runner.runtime_options`

#### Scenario: main()'s argparse setup reads the re-exported constants
- **WHEN** `run.py`'s `main()` builds `--analysts` (`default=DEFAULT_BACKTEST_ANALYSTS_ARG`) and `--personality` (`choices=VALID_PERSONALITIES`) arguments
- **THEN** it reads the same values as before the move, sourced from `runner.runtime_options`

