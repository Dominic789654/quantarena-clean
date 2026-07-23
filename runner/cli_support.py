"""CLI-facing print/formatting helpers extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-cli-support-helpers change (docs/refactor_program_plan.md
Phase 2). run.py re-exports every name here so existing `run.<name>`
monkeypatch string paths and `from run import <name>` imports keep
resolving.

These five functions are pure output formatting: they read already-
resolved arguments/result objects and print a summary (plus, for
`_print_backtest_result`, translate `result.errors` into an exit code).
None of them make backtest/multi-personality/pipeline orchestration
decisions or call into other run.py mode-handler functions -- that is
what distinguishes them from the mode handlers still in run.py (or,
after later Phase 2 steps, in `runner/modes/`), which is the boundary
this change draws per docs/refactor_program_plan.md step 10.

No standalone "logging setup helper" function was found in run.py to
move here: the only logging-related code is three lines inlined
directly in `run_deepear` (computing `run_id`/`log_dir` and calling
`utils.logging_setup.setup_file_logging`), which stays with that mode
handler.
"""

import argparse
from typing import Any, Dict, List, Optional


def print_banner() -> None:
    """Print application banner."""
    banner = """
    ╔════════════════════════════════════════════════════════════╗
    ║         Unified Agent Trading System                         ║
    ║    DeepEar Intelligence + DeepFund Trading Analysis         ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def _print_backtest_mode_config(
    args: argparse.Namespace,
    analysts: Optional[List[str]],
    *,
    market: Optional[str] = None,
    cashflow: Optional[float] = None,
    personality: Optional[str] = None,
    use_llm: Optional[bool] = None,
    benchmark: Optional[Dict[str, Any]] = None,
) -> None:
    """Print backtest mode configuration summary."""
    effective_market = market or args.market
    effective_cashflow = args.cashflow if cashflow is None else cashflow
    effective_personality = personality or args.personality
    effective_use_llm = args.use_llm if use_llm is None else use_llm

    effective_benchmark = dict(benchmark or {})
    benchmark_mode = effective_benchmark.get("mode", args.benchmark_mode)
    benchmark_index = effective_benchmark.get("index_code", args.benchmark_index)

    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Market: {effective_market}")
    print(f"Initial Capital: ${effective_cashflow:,.2f}")
    print(f"Benchmark Mode: {benchmark_mode}")
    if benchmark_index:
        print(f"Benchmark Index: {benchmark_index}")
    if effective_use_llm:
        print("\n[LLM Mode Enabled]")
        print(f"  Analysts: {analysts}")
        print(f"  Personality: {effective_personality}")
        print("  Note: Each day will call LLM APIs, incurring costs.")
    else:
        print("\n[Simple Mode: Buy-and-hold strategy]")
    if args.prefetch_only:
        print("\n[Prefetch-only mode: downloading data without running backtest]")
    print("\n" + "-" * 60)


def _print_backtest_result(result: Any) -> int:
    """Print standard backtest result summary and return exit code."""
    print("\n" + "=" * 60)
    print("Backtest Results Summary")
    print("=" * 60)
    print(f"Run ID: {result.run_id}")
    print(f"Total Return: {result.metrics.get('total_return', 0):+.2f}%")
    print(f"Annualized Return: {result.metrics.get('annualized_return', 0):+.2f}%")
    print(f"Max Drawdown: {result.metrics.get('max_drawdown', 0):.2f}%")
    print(f"Sharpe Ratio: {result.metrics.get('sharpe_ratio', 0):.2f}")
    print(f"Total Trades: {result.metrics.get('total_trades', 0)}")
    print(f"Win Rate: {result.metrics.get('win_rate', 0):.1f}%")
    print(f"\nFinal Value: ${result.metrics.get('final_value', 0):,.2f}")
    print("\n" + "-" * 60)
    print(f"Reports saved to: reports/backtest/{result.run_id}/")
    print("  - backtest_report.md")
    print("  - equity_curve.png")
    print("  - trades.csv")
    print("  - metrics.json")
    print("=" * 60)
    if result.errors:
        print(f"\nWarnings/Errors ({len(result.errors)}):")
        for err in result.errors[:5]:
            print(f"  - {err}")
        if len(result.errors) > 5:
            print(f"  ... and {len(result.errors) - 5} more")
    return 0 if not result.errors else 1


def _print_multi_personality_config(
    args: argparse.Namespace,
    personalities: List[str],
    analysts: Optional[List[str]],
    *,
    market: str,
    cashflow: float,
) -> None:
    """Print multi-personality mode configuration summary."""
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Market: {market}")
    print(f"Initial Capital: ¥{cashflow:,.2f}")
    print("\n[Multi-Personality Mode Enabled]")
    print(f"  Personalities: {personalities}")
    print(f"  Analysts: {analysts}")
    print(f"  Max workers: {args.max_workers or 'auto'}")
    print("  Note: Data will be prefetched once and shared across all personalities.")
    print("\n" + "-" * 60)


def _print_multi_personality_results(comparison: Any, cashflow: float) -> None:
    """Print standard multi-personality comparison summary."""
    print("\n" + "=" * 60)
    print("Multi-Personality Backtest Results Summary")
    print("=" * 60)
    print(f"Run ID: {comparison.run_id}")
    print(f"Total Duration: {comparison.total_duration:.2f} seconds")
    print(f"Trading Days: {comparison.trading_days}")
    print("\n--- Performance Comparison ---")
    sorted_results = sorted(
        comparison.personality_results.values(),
        key=lambda x: x.total_return,
        reverse=True,
    )
    for i, result in enumerate(sorted_results, 1):
        final_value = cashflow * (1 + result.total_return / 100)
        print(f"\n{i}. {result.personality.upper()}:")
        print(f"   Return: {result.total_return:+.2f}%")
        print(f"   Max Drawdown: {result.max_drawdown:.2f}%")
        print(f"   Sharpe Ratio: {result.sharpe_ratio:.2f}")
        print(f"   Final Value: ¥{final_value:,.0f}")
        print(f"   Trades: {result.trade_count}")
        print(f"   Duration: {result.duration_seconds:.2f}s")
    print("\n" + "-" * 60)
    print(f"Detailed reports saved to: reports/multi_personality/{comparison.run_id}/")
    print("  - comparison_report.md (full analysis)")
    print("  - comparison_data.json (raw data)")
    print("  - personality_summary.csv (CSV summary)")
    print("=" * 60)
