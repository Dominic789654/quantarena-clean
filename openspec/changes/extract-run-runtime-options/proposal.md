## Why

Continuing the run.py decomposition (docs/refactor_program_plan.md Phase
2, step 3 of 8): `_resolve_backtest_runtime_options` and
`_resolve_multi_personality_runtime_options` are the CLI-args-plus-YAML
merge logic shared by backtest and multi-personality mode. They, and the
private helpers they alone call, form a self-contained "runtime options"
domain that can move as one unit now that config discovery
(`extract-run-config-discovery`) already lives in `runner/`.

## What Changes

- Add `runner/runtime_options.py` holding, moved verbatim from `run.py`:
  `_resolve_backtest_runtime_options`, `_resolve_multi_personality_runtime_options`,
  `_extract_market_from_config`, `_extract_tickers_from_config`,
  `_parse_tickers_arg`, `_parse_optional_csv`, `_parse_personalities_arg`.
- Also relocates the two module-level constants these functions
  reference by bare name, `DEFAULT_BACKTEST_ANALYSTS_ARG` and
  `VALID_PERSONALITIES` (`= list(VALID_PROFILE_NAMES)`), into the new
  module — see design.md for why this is required, not optional.
- `run.py` re-exports all seven functions and both constants from
  `runner.runtime_options`.
- No behavior change: identical merge precedence (explicit CLI flag >
  config file value > default), identical error messages.

## Capabilities

### New Capabilities
- `run-runtime-options`: CLI-args-plus-YAML-config merge logic for
  backtest and multi-personality runtime configuration (tickers,
  analysts, personality/personalities, market, cashflow, use_llm,
  benchmark).

### Modified Capabilities
- None.

## Impact

- `run.py`, new `runner/runtime_options.py`.
- Monkeypatch audit (ground rule 3):
  `git grep -n "monkeypatch" tests/ | grep -E
  "_resolve_backtest_runtime_options|_resolve_multi_personality_runtime_options|_extract_market_from_config|_extract_tickers_from_config|_parse_tickers_arg|_parse_optional_csv|_parse_personalities_arg|DEFAULT_BACKTEST_ANALYSTS_ARG|VALID_PERSONALITIES"`
  returns nothing — zero monkeypatch coverage on any of these seven
  functions or two constants.
  `tests/test_run_config_selection.py` and
  `tests/test_backtest_fof_config_runtime.py` do plain `from run import
  (DEFAULT_BACKTEST_ANALYSTS_ARG, DEFAULT_MULTI_PERSONALITIES_ARG,
  _resolve_backtest_runtime_options, _resolve_multi_personality_runtime_options,
  ...)` — satisfied by the re-export.
  `_execute_backtest_mode`, `run_multi_personality_mode`, and `main()`
  (all monkeypatched via `run.<name>` elsewhere in
  `test_backtest_fof_config_runtime.py`) stay in `run.py` unchanged in
  this change and call the two resolvers by bare name — those calls
  resolve fine against `run.py`'s re-exported globals, no shim needed.
  `_validate_backtest_date_range`, `_print_backtest_mode_config`,
  `_execute_backtest_mode`, `_print_multi_personality_config` also stay
  in `run.py` (out of scope; slated for a later Phase 2 step) and are
  interleaved between the moved definitions in the source file, so the
  move required several separate one-line import insertions rather than
  one contiguous block replacement — each verified individually.
