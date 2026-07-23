## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "monkeypatch.setattr" tests/ | grep "run\."`
  restricted to names `main()` calls -- `run.print_banner` and
  `run.run_backtest_mode` both patched at
  `test_backtest_fof_config_runtime.py:55-56`, both while calling
  `run.main()` directly. **Shim both.**
- [x] 1.2 Confirm `check_env_file`, `run_deepear`, `run_deepfund`,
  `run_full_pipeline`, `run_multi_personality_mode` have zero `run.*`
  monkeypatch coverage in the context of a `main()` call -- no shim
  for those five.

## 2. Implementation

- [x] 2.1 Add `runner/cli.py` with `DEFAULT_MULTI_PERSONALITIES_ARG`
  and `main()` moved verbatim, importing every dependency directly
  from its owning `runner/` submodule (never from `run.py`), and
  routing the `print_banner()` and `run_backtest_mode(args)` calls
  through `runner._shim.run_module()`.
- [x] 2.2 Rewrite `run.py` as a thin shim: the tushare-fix bootstrap
  call, `setup_paths()`, one consolidated re-export block covering
  every name previously defined in `run.py` (now sourced from
  `runner.env_validation`, `runner.config_discovery`,
  `runner.runtime_options`, `runner.cli_support`, `runner.modes.*`, and
  `runner.cli`), and `if __name__ == "__main__": sys.exit(main())`.
- [x] 2.3 Drop `run.py`'s now-unused `import argparse` (argparse
  construction lives entirely in `runner/cli.py` now).

## 3. Verification

- [x] 3.1 Experimentally confirmed the `run_backtest_mode` shim in
  `main()` is load-bearing: temporarily reverted the
  `args.mode == "backtest"` branch to a bare `run_backtest_mode(args)`
  call and re-ran `test_main_marks_benchmark_cli_flags_explicit` in
  isolation -- it failed with `KeyError: 'benchmark_mode_explicit'`
  (a real backtest ran instead of the test's fake). Restored the shim;
  re-ran -- passed.
- [x] 3.2 `.venv_unified/bin/python -m pytest tests/ -q` -- 935 passed
  (baseline unchanged; no new tests in this change), 10 skipped, 0
  failed.
- [x] 3.3 `.venv_unified/bin/ruff check .` clean.
- [x] 3.4 `python run.py --check-env` exits 0.
- [x] 3.5 `python run.py --help` exits 0 and prints the full argparse
  usage (real end-to-end invocation of `runner.cli.main`'s parser, not
  just an import-level check).
- [x] 3.6 `python run.py --mode full --skip-deepear --skip-deepfund
  --no-banner` exits 0.
- [x] 3.7 `run.py`'s final line count: 75 (from 1218 at the start of
  the program, 779 at the start of Phase 2).
