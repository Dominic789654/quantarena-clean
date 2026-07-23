# run-cli-entrypoint Specification

## Purpose
TBD - created by archiving change extract-run-cli-entrypoint-package. Update Purpose after archive.
## Requirements
### Requirement: main() dispatches to a mode handler chosen by --mode, observing monkeypatches applied to the public run module
`runner.cli.main` SHALL build an argparse parser exposing `--mode` (choices: `deepear`, `deepfund`, `full`, `backtest`, `multi-personality`; default `deepear`) plus the DeepEar/DeepFund/pipeline/backtest/multi-personality/environment options, SHALL short-circuit and return `0` when `--check-env` is passed (printing a success or warning message based on `check_env_file()`), SHALL otherwise print the banner (unless `--no-banner`) and dispatch to the mode handler matching `args.mode`, and SHALL resolve its calls to `print_banner` and `run_backtest_mode` through `runner._shim.run_module()` so a `monkeypatch.setattr("run.<name>", fake)` is observed even though `main()` is defined in `runner.cli`, not `run.py`.

#### Scenario: --check-env short-circuits before banner or mode dispatch
- **WHEN** `args.check_env` is `True`
- **THEN** `main()` returns `0` (or otherwise reflects `check_env_file()`'s result) without calling `print_banner` or any mode handler

#### Scenario: A monkeypatched run_backtest_mode is observed when dispatching backtest mode
- **WHEN** a test does `monkeypatch.setattr("run.run_backtest_mode", fake)` and then calls `run.main()` with `--mode backtest`
- **THEN** `main()` invokes `fake`, not its own local `run_backtest_mode` import, and returns `fake`'s return value

#### Scenario: A monkeypatched print_banner is observed unless --no-banner is set
- **WHEN** a test does `monkeypatch.setattr("run.print_banner", fake)` and calls `run.main()` without `--no-banner`
- **THEN** `main()` invokes `fake` before dispatching to the mode handler

#### Scenario: _market_explicit and sibling flags are computed from raw argv
- **WHEN** `main()` parses arguments
- **THEN** it sets `args._market_explicit`, `args._analysts_explicit`, `args._benchmark_mode_explicit`, and `args._benchmark_index_explicit` to whether the corresponding `--flag`/`--flag=value` token appears literally in `sys.argv[1:]`, independent of argparse's own default-vs-provided tracking

### Requirement: run.py is a thin shim collapsing to bootstrap calls, a re-export block, and the __main__ guard
`run.py` SHALL contain no function or class definitions of its own (other than the historical tushare-fix bootstrap sequence, which stays inline per prior Phase 2 changes), SHALL re-export every name that any test imports via `from run import <name>` or patches via `monkeypatch.setattr("run.<name>", ...)`, and SHALL end with `if __name__ == "__main__": sys.exit(main())` where `main` is imported from `runner.cli`.

#### Scenario: python run.py executes main() as __main__
- **WHEN** `run.py` is executed directly (`python run.py --check-env`)
- **THEN** Python registers the module as `__main__` (not `run`), and `runner._shim.run_module()`'s `sys.modules.get("__main__")` fallback branch is the one that resolves during any shimmed call inside `runner.cli.main`

#### Scenario: Every pre-decomposition public name remains importable from run
- **WHEN** any test does `from run import <name>` for any name that was defined directly in `run.py` before Phase 2 began
- **THEN** the import succeeds, resolving to the re-exported attribute backed by the appropriate `runner/` submodule

