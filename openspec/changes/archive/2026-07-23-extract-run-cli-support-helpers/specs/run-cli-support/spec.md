## ADDED Requirements

### Requirement: Backtest result printing translates errors into an exit code
`runner.cli_support._print_backtest_result` SHALL print a formatted summary of a backtest result's run id and metrics, SHALL print up to 5 of `result.errors` (with a count of any remainder) when errors are present, and SHALL return `0` when `result.errors` is empty and `1` otherwise.

#### Scenario: Result with no errors returns 0
- **WHEN** `result.errors` is an empty list
- **THEN** `_print_backtest_result` returns `0` and prints no warnings/errors section

#### Scenario: Result with more than 5 errors truncates the printed list
- **WHEN** `result.errors` has 7 entries
- **THEN** the first 5 are printed individually and a line reporting "... and 2 more" is printed, and the function returns `1`

### Requirement: Configuration summary printers resolve CLI-vs-runtime precedence for display
`runner.cli_support._print_backtest_mode_config` and `runner.cli_support._print_multi_personality_config` SHALL print the period, market, initial capital, and mode-specific settings (LLM/analysts/personality for backtest; personalities/analysts/max-workers for multi-personality) using the resolved runtime values when provided, falling back to the raw `args` values otherwise.

#### Scenario: Backtest config printer prefers resolved runtime market over raw args
- **WHEN** `_print_backtest_mode_config` is called with `market="us"` while `args.market == "cn"`
- **THEN** the printed "Market:" line shows "us"

### Requirement: run.py re-exports CLI support helpers
`run.py` SHALL expose `print_banner`, `_print_backtest_mode_config`, `_print_backtest_result`, `_print_multi_personality_config`, and `_print_multi_personality_results` as module attributes re-exported from `runner.cli_support`, so existing `run.<name>` monkeypatch string paths and `from run import <name>` imports continue to resolve.

#### Scenario: Existing monkeypatch paths keep working
- **WHEN** a test does `monkeypatch.setattr("run._print_backtest_result", fake)` or `monkeypatch.setattr("run.print_banner", fake)`
- **THEN** `_execute_backtest_mode` and `main()` (both still defined in `run.py` as of this change) observe `fake`, because they call these names bare within `run.py`'s own namespace
