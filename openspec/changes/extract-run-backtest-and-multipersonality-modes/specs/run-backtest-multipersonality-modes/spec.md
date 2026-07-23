## ADDED Requirements

### Requirement: Backtest mode execution observes monkeypatches applied to the public run module
`runner.modes.backtest._execute_backtest_mode` SHALL invoke `_validate_backtest_date_range`, `_validate_backtest_environment_for_runtime`, and `_print_backtest_result` by resolving each through `runner._shim.run_module()` first (falling back to its own local import when the shim finds no usable module), so that a test's `monkeypatch.setattr("run.<name>", fake)` is observed even though `_execute_backtest_mode` is defined in `runner.modes.backtest`, not `run.py`.

#### Scenario: A monkeypatched validator short-circuits backtest execution
- **WHEN** a test does `monkeypatch.setattr("run._validate_backtest_environment_for_runtime", lambda runtime: False)` and then calls `_execute_backtest_mode(args, run_backtest)` directly
- **THEN** `_execute_backtest_mode` returns `1` without calling `run_backtest`, because it observed the fake, not its own local `_validate_backtest_environment_for_runtime`

#### Scenario: A monkeypatched result printer is observed
- **WHEN** a test does `monkeypatch.setattr("run._print_backtest_result", lambda result: 0)` and `_execute_backtest_mode` completes a non-prefetch-only run
- **THEN** the fake, not the real `_print_backtest_result`, determines the returned exit code

### Requirement: Multi-personality mode execution observes monkeypatches applied to the public run module
`runner.modes.multi_personality.run_multi_personality_mode` SHALL invoke `_validate_backtest_date_range`, `_validate_backtest_environment_for_runtime`, and `_print_multi_personality_results` by resolving each through `runner._shim.run_module()` first, for the same reason and with the same fallback behavior as `_execute_backtest_mode`.

#### Scenario: A monkeypatched runtime validator observes the resolved runtime
- **WHEN** a test does `monkeypatch.setattr("run._validate_backtest_environment_for_runtime", fake)` (where `fake` records its argument and returns `False`) and then calls `run_multi_personality_mode(args)` directly
- **THEN** `run_multi_personality_mode` returns `1`, `fake` was called with the resolved `runtime` dict, and `backtest.multi_personality_engine.run_multi_personality_backtest` is never invoked

### Requirement: run.py re-exports the backtest and multi-personality mode handlers
`run.py` SHALL expose `_validate_backtest_date_range`, `_execute_backtest_mode`, `run_backtest_mode`, and `run_multi_personality_mode` as module attributes re-exported from `runner.modes.backtest` and `runner.modes.multi_personality`, so existing `run.<name>` monkeypatch string paths and `from run import <name>` imports continue to resolve.

#### Scenario: main()'s bare-name call to run_backtest_mode still resolves against run.py's re-export
- **WHEN** a test does `monkeypatch.setattr("run.run_backtest_mode", fake)` and then calls `run.main()` with `--mode backtest`
- **THEN** `main()` (still defined in `run.py` as of this change) invokes `fake`, because it calls `run_backtest_mode` bare within `run.py`'s own namespace
