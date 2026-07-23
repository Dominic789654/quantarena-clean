"""Backtest mode handler extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-backtest-and-multipersonality-modes change
(docs/refactor_program_plan.md Phase 2). run.py re-exports
`_validate_backtest_date_range`, `_execute_backtest_mode`, and
`run_backtest_mode` so existing `run.<name>` monkeypatch string paths
and `from run import <name>` imports keep resolving.

This module has the highest monkeypatch density of any Phase 2 step:
`tests/test_backtest_fof_config_runtime.py` patches
`run._validate_backtest_environment_for_runtime` and
`run._print_backtest_result` while calling `_execute_backtest_mode`
directly. Both callees now live in other `runner/` modules
(`runner.env_validation`, `runner.cli_support`); a plain bare-name call
from `_execute_backtest_mode` would resolve against *this* module's own
imported reference, silently ignoring a patch applied to `run.py`'s
re-export. Both calls are routed through `runner._shim.run_module()`
(falling back to the local import when no `run`/`__main__` module is
found), exactly like `runner/env_validation.py`'s
`_validate_backtest_environment_for_runtime` -> `_validate_environment`
call.

`_validate_backtest_date_range` is also patched on `run.*`
(`test_run_multi_personality_mode_validates_after_runtime_resolution`,
`test_run_multi_personality_mode_passes_resolved_fof_runtime`) via its
*other* caller, `run_multi_personality_mode` (see
`runner/modes/multi_personality.py`). Since that patch-sensitivity
attaches to the function itself, not to one specific caller, this
module's own call to it from `_execute_backtest_mode` is routed through
the shim too, for the same reason `_validate_backtest_environment_for_runtime`
and `_print_backtest_result` are.

`_print_backtest_mode_config` and `_resolve_backtest_runtime_options`
have zero `run.*` monkeypatch coverage (grep confirmed -- see the
change's proposal.md audit), so their calls stay plain bare-name calls
against this module's own imports.
"""

import argparse
from datetime import datetime
from typing import Any, Optional

from runner import _shim
from runner.cli_support import _print_backtest_mode_config, _print_backtest_result
from runner.env_validation import _validate_backtest_environment_for_runtime
from runner.runtime_options import _resolve_backtest_runtime_options


def _validate_backtest_date_range(start_date: Optional[str], end_date: Optional[str], mode_name: str) -> bool:
    """Validate CLI date args for backtesting modes."""
    if not start_date or not end_date:
        print(f"ERROR: --start-date and --end-date are required for {mode_name}")
        print("Example: --start-date 2024-01-01 --end-date 2024-01-31")
        return False
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        if start > end:
            print("ERROR: start-date must be before end-date")
            return False
    except ValueError as e:
        print(f"ERROR: Invalid date format: {e}. Use YYYY-MM-DD.")
        return False
    return True


def _execute_backtest_mode(args: argparse.Namespace, run_backtest: Any) -> int:
    """Execute backtest mode after imports are ready."""
    # Route through the public `run` module (or __main__) so that
    # monkeypatch.setattr("run._validate_backtest_date_range", ...) is
    # honored even though this function now lives in runner/, not run.py.
    validate_date_range = (
        getattr(_shim.run_module(), "_validate_backtest_date_range", None) or _validate_backtest_date_range
    )
    if not validate_date_range(args.start_date, args.end_date, mode_name="backtest mode"):
        return 1
    try:
        runtime = _resolve_backtest_runtime_options(args)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    validate_environment_for_runtime = (
        getattr(_shim.run_module(), "_validate_backtest_environment_for_runtime", None)
        or _validate_backtest_environment_for_runtime
    )
    if not validate_environment_for_runtime(runtime):
        return 1
    _print_backtest_mode_config(
        args,
        runtime["analysts"],
        market=runtime["market"],
        cashflow=runtime["cashflow"],
        personality=runtime["personality"],
        use_llm=runtime["use_llm"],
        benchmark=runtime["config"].get("benchmark"),
    )
    if runtime["config_path"]:
        print(f"Using config: {runtime['config_path']}")
    result = run_backtest(
        tickers=runtime["tickers"],
        start_date=args.start_date,
        end_date=args.end_date,
        initial_cash=runtime["cashflow"],
        market=runtime["market"],
        prefetch_only=args.prefetch_only,
        config=runtime["config"],
        use_llm=runtime["use_llm"],
        analysts=runtime["analysts"],
        personality=runtime["personality"],
    )
    if args.prefetch_only:
        print("\n" + "=" * 60)
        print("Data prefetch completed!")
        print("=" * 60)
        return 0
    print_backtest_result = getattr(_shim.run_module(), "_print_backtest_result", None) or _print_backtest_result
    return print_backtest_result(result) if result else 1


def run_backtest_mode(args: argparse.Namespace) -> int:
    """Run backtesting simulation."""
    print("\n" + "=" * 60)
    print("Mode: Backtesting")
    print("=" * 60 + "\n")

    try:
        from backtest.engine import run_backtest
        return _execute_backtest_mode(args, run_backtest)

    except ImportError as e:
        print(f"ERROR: Failed to import backtest modules: {e}")
        print("Make sure the backtest module is properly installed.")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"ERROR: Backtest execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
