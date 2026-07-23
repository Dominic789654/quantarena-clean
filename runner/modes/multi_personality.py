"""Multi-personality mode handler extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-backtest-and-multipersonality-modes change
(docs/refactor_program_plan.md Phase 2). run.py re-exports
`run_multi_personality_mode` so existing `run.<name>` monkeypatch
string paths and `from run import <name>` imports keep resolving.

`tests/test_backtest_fof_config_runtime.py` patches
`run._validate_backtest_date_range`,
`run._validate_backtest_environment_for_runtime`, and
`run._print_multi_personality_results` while calling
`run_multi_personality_mode` directly
(`test_run_multi_personality_mode_validates_after_runtime_resolution`,
`test_run_multi_personality_mode_passes_resolved_fof_runtime`). All
three callees live outside this module (`_validate_backtest_date_range`
in the sibling `runner.modes.backtest`; the other two in
`runner.env_validation`/`runner.cli_support`), so a plain bare-name call
would resolve against this module's own imported reference, silently
ignoring a patch applied to `run.py`'s re-export. All three calls are
routed through `runner._shim.run_module()`, mirroring
`runner/modes/backtest.py`'s identical treatment of the same two
env-validation/date-range functions.

`_print_multi_personality_config` and
`_resolve_multi_personality_runtime_options` have zero `run.*`
monkeypatch coverage (grep confirmed -- see the change's proposal.md
audit), so their calls stay plain bare-name calls against this module's
own imports.
"""

import argparse

from runner import _shim
from runner.cli_support import _print_multi_personality_config, _print_multi_personality_results
from runner.env_validation import _validate_backtest_environment_for_runtime
from runner.modes.backtest import _validate_backtest_date_range
from runner.runtime_options import _resolve_multi_personality_runtime_options


def run_multi_personality_mode(args: argparse.Namespace) -> int:
    """Run multi-personality parallel backtesting."""
    print("\n" + "=" * 60)
    print("Mode: Multi-Personality Parallel Backtesting")
    print("=" * 60 + "\n")

    try:
        from backtest.multi_personality_engine import run_multi_personality_backtest

        # Route through the public `run` module (or __main__) so that
        # monkeypatch.setattr("run._validate_backtest_date_range", ...)
        # is honored even though this function now lives in runner/,
        # not run.py.
        validate_date_range = (
            getattr(_shim.run_module(), "_validate_backtest_date_range", None) or _validate_backtest_date_range
        )
        if not validate_date_range(args.start_date, args.end_date, mode_name="multi-personality mode"):
            return 1
        try:
            runtime = _resolve_multi_personality_runtime_options(args)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        validate_environment_for_runtime = (
            getattr(_shim.run_module(), "_validate_backtest_environment_for_runtime", None)
            or _validate_backtest_environment_for_runtime
        )
        if not validate_environment_for_runtime(runtime):
            return 1

        _print_multi_personality_config(
            args,
            runtime["personalities"],
            runtime["analysts"],
            market=runtime["market"],
            cashflow=runtime["cashflow"],
        )
        if runtime["config_path"]:
            print(f"Using config: {runtime['config_path']}")

        comparison = run_multi_personality_backtest(
            tickers=runtime["tickers"],
            start_date=args.start_date,
            end_date=args.end_date,
            personalities=runtime["personalities"],
            initial_cash=runtime["cashflow"],
            market=runtime["market"],
            analysts=runtime["analysts"],
            db_path="data/signal_flux.db",
            config=runtime["config"],
            use_llm=runtime["use_llm"],
            max_workers=args.max_workers,
        )
        print_multi_personality_results = (
            getattr(_shim.run_module(), "_print_multi_personality_results", None)
            or _print_multi_personality_results
        )
        print_multi_personality_results(comparison, runtime["cashflow"])
        return 0

    except ImportError as e:
        print(f"ERROR: Failed to import multi-personality modules: {e}")
        print("Make sure the backtest module is properly installed.")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"ERROR: Multi-personality backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
