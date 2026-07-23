## Why

Continuing the run.py decomposition (docs/refactor_program_plan.md Phase
2, step 5 of 8): with env validation, config discovery, and runtime
options already moved to `runner/`, the remaining non-mode-handler
functions in run.py are five small print/format helpers
(`print_banner`, `_print_backtest_mode_config`, `_print_backtest_result`,
`_print_multi_personality_config`, `_print_multi_personality_results`).
None of them decide backtest/multi-personality/pipeline control flow;
they only format already-resolved data for stdout. Extracting them now
(before the mode handlers themselves move in steps 6-7) keeps run.py's
remaining body limited to mode handlers and `main()`.

## What Changes

- Add `runner/cli_support.py` holding, moved verbatim from `run.py`:
  `print_banner`, `_print_backtest_mode_config`, `_print_backtest_result`,
  `_print_multi_personality_config`, `_print_multi_personality_results`.
- `run.py` re-exports all five from `runner.cli_support`.
- No behavior change: identical output formatting, identical exit-code
  logic in `_print_backtest_result`.

## Capabilities

### New Capabilities
- `run-cli-support`: stdout formatting helpers for the banner, backtest
  mode configuration/result summaries, and multi-personality mode
  configuration/result summaries -- pure presentation, no
  orchestration.

### Modified Capabilities
- None.

## Impact

- `run.py`, new `runner/cli_support.py`.
- Monkeypatch audit (ground rule 3):
  `git grep -n "monkeypatch" tests/ | grep -E
  "print_banner|_print_backtest_mode_config|_print_backtest_result|_print_multi_personality_config|_print_multi_personality_results"`
  finds `run._print_backtest_result` patched at
  `test_backtest_fof_config_runtime.py:231,259,443` and
  `run.print_banner` patched at `:56`. In every case the *caller*
  (`_execute_backtest_mode`, `main()`) still lives in `run.py` after
  this change (both are out of scope until steps 7 and 8), so the
  internal bare-name calls still resolve against `run.py`'s own
  re-exported globals -- the patches keep working with no `_shim`
  indirection needed here. This will change once `_execute_backtest_mode`
  itself moves out of `run.py` (step 7) and `main()` moves out (step
  8): those two later changes are the ones that must route these same
  calls through `runner/_shim.py`.
- `_print_multi_personality_config`/`_print_multi_personality_results`
  have no monkeypatch coverage; `_print_backtest_mode_config` has none
  either.
- No standalone "logging setup helper" function exists in run.py to
  move: the only logging-related code is three lines inlined directly
  in `run_deepear` (a mode handler, out of scope for this change).
