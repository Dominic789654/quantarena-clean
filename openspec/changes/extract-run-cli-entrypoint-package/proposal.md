## Why

This is the final step of the run.py decomposition
(docs/refactor_program_plan.md Phase 2, step 8 of 8). `main()` and its
~250-line argparse construction are the last things defined in run.py.
Moving them out completes the plan: run.py becomes a thin shim
(bootstrap calls + a re-export block + the `__main__` guard) and every
implementation lives in `runner/`.

## What Changes

- Add `runner/cli.py` holding, moved verbatim from `run.py`: `main()`
  (including the full argparse setup) and
  `DEFAULT_MULTI_PERSONALITIES_ARG` (the one CLI-only constant that
  lived alongside it, used only as `main()`'s `--personalities`
  default).
- `main()`'s calls to `print_banner` and `run_backtest_mode` are routed
  through `runner._shim.run_module()`.
- `run.py` collapses to: the tushare-fix bootstrap call, `setup_paths()`,
  one consolidated re-export block importing every name that used to be
  defined directly in run.py (now spread across `runner/env_validation.py`,
  `runner/config_discovery.py`, `runner/runtime_options.py`,
  `runner/cli_support.py`, `runner/modes/*.py`, and the new
  `runner/cli.py`), and `if __name__ == "__main__": sys.exit(main())`.
  run.py drops to 75 lines (from 1218 at the start of the program, 779
  at the start of this phase).
- No behavior change: identical argparse flags/defaults/choices,
  identical mode-dispatch logic, identical `--check-env` short-circuit.

## Capabilities

### New Capabilities
- `run-cli-entrypoint`: the `main()` CLI entrypoint -- argparse
  construction, the `--check-env` short-circuit, banner printing, and
  dispatch to the five execution modes.

### Modified Capabilities
- None.

## Impact

- `run.py`, new `runner/cli.py`.
- Monkeypatch audit (ground rule 3):
  `git grep -n "monkeypatch.setattr" tests/ | grep "run\\."` restricted
  to names `main()` calls: `run.print_banner` and `run.run_backtest_mode`
  are both patched at `test_backtest_fof_config_runtime.py:55-56`
  (`test_main_marks_benchmark_cli_flags_explicit`), which calls
  `run.main()` directly. Both are **shimmed**. `check_env_file`,
  `run_deepear`, `run_deepfund`, `run_full_pipeline`, and
  `run_multi_personality_mode` have zero `run.*` monkeypatch coverage
  in the context of a `main()` call -- their calls stay plain bare-name
  calls.
- `tests/test_run_subprocess_smoke.py` (real `subprocess.run([sys.
  executable, "run.py", "--check-env"])`) and
  `tests/test_type_annotations.py::test_main_has_return_annotation`
  (`from run import main`) both continue to pass unchanged -- the
  subprocess test in particular is the one test that exercises the
  `sys.modules.get("__main__")` fallback branch of `runner._shim.run_module()`,
  now doubly relevant since `main()` itself has moved out of the module
  that gets registered as `__main__`.
- Experimentally verified the `run_backtest_mode` shim in `main()` is
  load-bearing: temporarily reverted the `args.mode == "backtest"`
  branch to a bare `run_backtest_mode(args)` call (bypassing `_shim`)
  and re-ran `test_main_marks_benchmark_cli_flags_explicit` in
  isolation -- it failed with `KeyError: 'benchmark_mode_explicit'`
  (the real, unpatched `run_backtest_mode` ran an actual backtest
  against `data/signal_flux.db` -- log lines show a real
  `BacktestEngine`/`DataPrefetcher`/`PortfolioTracker` run completing --
  instead of the test's fake, so `captured` stayed an empty dict and
  the assertion on `captured["benchmark_mode_explicit"]` raised
  `KeyError` rather than a plain `assert False` mismatch). Restored the
  shim; re-ran -- passed.
