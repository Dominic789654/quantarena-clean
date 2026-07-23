#!/usr/bin/env python3
"""
Unified Agent Trading - Main Entry Point
==========================================
Combines DeepEar (intelligence gathering) and DeepFund (trading analysis)
"""

import argparse
import sys
from datetime import datetime
from typing import Optional, Any

# Fix Tushare's tk.csv issue BEFORE any other imports!
from runner.bootstrap import _fix_tushare_token_file, load_dotenv_file  # noqa: F401

# Apply the fix FIRST, before any other imports
_fix_tushare_token_file()

# Setup project paths using unified path manager
from shared.utils.path_manager import (
    get_deepfund_src,
    get_project_root,
    setup_paths,
)
from shared.utils.time_utils import now_utc
setup_paths()

# Shared path handles used across run modes
PROJECT_ROOT = get_project_root()
DEEPFUND_SRC = get_deepfund_src()
from runner.runtime_options import DEFAULT_BACKTEST_ANALYSTS_ARG  # noqa: F401,E402
DEFAULT_MULTI_PERSONALITIES_ARG = "conservative,balanced,aggressive,passive"

# Import stats for usage tracking
from deepear.src.utils.stats import get_stats


from runner.env_validation import (  # noqa: F401
    _validate_environment,
    _print_backtest_env_error,
    _configured_us_data_provider,
    _validate_non_llm_backtest_environment,
    _validate_backtest_environment_for_runtime,
    check_env_file,
)


from runner.config_discovery import (  # noqa: F401
    _get_deepfund_config_candidates,
    _load_yaml_config_file,
    _select_backtest_config_file,
)


from runner.runtime_options import (  # noqa: F401
    _extract_market_from_config,
    _extract_tickers_from_config,
    _resolve_backtest_runtime_options,
    _resolve_multi_personality_runtime_options,
)


from runner.cli_support import print_banner  # noqa: F401


def run_deepear(args: argparse.Namespace) -> int:
    """Run DeepEar intelligence gathering."""
    # Validate environment for deepear mode
    if not _validate_environment(mode="deepear"):
        return 1
    
    print("\n" + "=" * 60)
    print("Mode: DeepEar Intelligence Gathering")
    print("=" * 60 + "\n")

    try:
        # Import DeepEar modules
        from main_flow import SignalFluxWorkflow
        from utils.logging_setup import setup_file_logging, make_run_id

        # Setup logging
        run_id = args.run_id or make_run_id()
        log_dir = args.log_dir or str(PROJECT_ROOT / "logs")
        log_path = setup_file_logging(run_id=run_id, log_dir=log_dir, level=args.log_level)

        print(f"Log file: {log_path}")
        print(f"Run ID: {run_id}")

        # Parse sources
        if args.sources.lower() in ["all", "financial", "social", "tech"]:
            sources = [args.sources]
        else:
            sources = [s.strip() for s in args.sources.split(",")]

        # Parse depth
        depth = args.depth
        try:
            depth = int(depth)
        except ValueError:
            pass  # Keep as 'auto' or original string

        # Create workflow
        workflow = SignalFluxWorkflow(isq_template_id=args.template or "default_isq_v1")

        # Run workflow
        result = workflow.run(
            sources=sources,
            wide=args.wide or 10,
            depth=depth,
            query=args.query or "扫描A股市场热点",
            run_id=run_id,
            checkpoint_dir=args.checkpoint_dir or str(PROJECT_ROOT / "reports" / "checkpoints"),
            resume=args.resume,
            resume_from=args.resume_from or "report",
            concurrency=args.concurrency or 1,
        )

        print(f"\n{'=' * 60}")
        print("DeepEar completed successfully!")
        print(f"Output: {result}")
        return 0

    except ImportError as e:
        print(f"ERROR: Failed to import DeepEar modules: {e}")
        print("Make sure DeepEar is properly installed.")
        return 1
    except Exception as e:
        print(f"ERROR: DeepEar execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def run_deepfund(args: argparse.Namespace) -> int:
    """Run DeepFund trading analysis."""
    # Validate environment for deepfund mode
    if not _validate_environment(mode="deepfund"):
        return 1
    
    print("\n" + "=" * 60)
    print("Mode: DeepFund Trading Analysis")
    print("=" * 60 + "\n")

    try:
        # Import DeepFund modules
        # main.py is directly in deepfund/src/
        import importlib.util
        main_path = DEEPFUND_SRC / "main.py"
        spec = importlib.util.spec_from_file_location("deepfund_main", main_path)
        deepfund_main_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(deepfund_main_module)
        deepfund_main = deepfund_main_module.main

        # Load environment
        load_dotenv_file(PROJECT_ROOT / ".env")

        # Determine config file
        config_file = args.config
        if not config_file:
            config_candidates = _get_deepfund_config_candidates(args.market)

            # Find first existing config
            for cfg in config_candidates:
                if cfg.exists():
                    config_file = str(cfg)
                    break
            else:
                config_file = str(config_candidates[0])

        print(f"Using config: {config_file}")

        # Parse trading date
        trading_date = args.date
        if not trading_date:
            # Default to today or last trading day
            trading_date = now_utc().strftime("%Y-%m-%d")

        try:
            datetime.strptime(trading_date, "%Y-%m-%d")
        except ValueError:
            print(f"ERROR: Invalid date format: {trading_date}. Use YYYY-MM-DD.")
            return 1

        # Build sys.argv for deepfund_main
        sys.argv = [
            "deepfund",
            "--config", config_file,
            "--trading-date", trading_date,
        ]
        if args.local_db:
            sys.argv.append("--local-db")

        # Run DeepFund
        deepfund_main()

        print(f"\n{'=' * 60}")
        print("DeepFund completed successfully!")
        return 0

    except ImportError as e:
        print(f"ERROR: Failed to import DeepFund modules: {e}")
        print("Make sure DeepFund is properly installed.")
        return 1
    except Exception as e:
        print(f"ERROR: DeepFund execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def run_full_pipeline(args: argparse.Namespace) -> int:
    """Run complete pipeline: DeepEar + DeepFund."""
    print("\n" + "=" * 60)
    print("Mode: Full Pipeline (DeepEar + DeepFund)")
    print("=" * 60 + "\n")

    exit_code = 0

    # Phase 1: DeepEar Intelligence
    if not args.skip_deepear:
        deepear_exit = run_deepear(args)
        if deepear_exit != 0 and not args.continue_on_error:
            return deepear_exit
        exit_code = max(exit_code, deepear_exit)
    else:
        print("Skipping DeepEar phase...")

    # Phase 2: DeepFund Trading
    if not args.skip_deepfund:
        deepfund_exit = run_deepfund(args)
        if deepfund_exit != 0 and not args.continue_on_error:
            return deepfund_exit
        exit_code = max(exit_code, deepfund_exit)
    else:
        print("Skipping DeepFund phase...")

    print("\n" + "=" * 60)
    print("Full Pipeline completed!")
    print(f"{'=' * 60}")

    # 打印使用统计报告
    get_stats().print_report()

    return exit_code


from runner.runtime_options import VALID_PERSONALITIES, _parse_tickers_arg  # noqa: F401


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


from runner.runtime_options import _parse_optional_csv  # noqa: F401


from runner.cli_support import _print_backtest_mode_config, _print_backtest_result  # noqa: F401


def _execute_backtest_mode(args: argparse.Namespace, run_backtest: Any) -> int:
    """Execute backtest mode after imports are ready."""
    if not _validate_backtest_date_range(args.start_date, args.end_date, mode_name="backtest mode"):
        return 1
    try:
        runtime = _resolve_backtest_runtime_options(args)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    if not _validate_backtest_environment_for_runtime(runtime):
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
    return _print_backtest_result(result) if result else 1


from runner.runtime_options import _parse_personalities_arg  # noqa: F401


from runner.cli_support import (  # noqa: F401
    _print_multi_personality_config,
    _print_multi_personality_results,
)


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


def run_multi_personality_mode(args: argparse.Namespace) -> int:
    """Run multi-personality parallel backtesting."""
    print("\n" + "=" * 60)
    print("Mode: Multi-Personality Parallel Backtesting")
    print("=" * 60 + "\n")

    try:
        from backtest.multi_personality_engine import run_multi_personality_backtest

        if not _validate_backtest_date_range(args.start_date, args.end_date, mode_name="multi-personality mode"):
            return 1
        try:
            runtime = _resolve_multi_personality_runtime_options(args)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        if not _validate_backtest_environment_for_runtime(runtime):
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
        _print_multi_personality_results(comparison, runtime["cashflow"])
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


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified Agent Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Execution mode
    parser.add_argument(
        "--mode",
        type=str,
        choices=["deepear", "deepfund", "full", "backtest", "multi-personality"],
        default="deepear",
        help="Execution mode: deepear (intelligence), deepfund (trading), full (both), backtest, or multi-personality"
    )

    # DeepEar options
    parser.add_argument(
        "--query",
        type=str,
        help="User query/intent for DeepEar analysis"
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="all",
        help="News sources: all, financial, social, tech, or comma-separated list"
    )
    parser.add_argument(
        "--wide",
        type=int,
        default=10,
        help="Number of news items per source"
    )
    parser.add_argument(
        "--depth",
        type=str,
        default="auto",
        help="Report depth: auto or integer limit"
    )
    parser.add_argument(
        "--template",
        type=str,
        default="default_isq_v1",
        help="ISQ template ID"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max workers for signal analysis"
    )
    parser.add_argument(
        "--run-id",
        type=str,
        help="Custom run ID for logging"
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        help="Log directory"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log level"
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=str,
        help="Checkpoint directory"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint"
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default="report",
        choices=["report", "analysis"],
        help="Resume from specific checkpoint stage"
    )
    parser.add_argument(
        "--update-from",
        type=str,
        help="Update from previous run ID"
    )

    # DeepFund options
    parser.add_argument(
        "--market",
        type=str,
        choices=["cn", "us"],
        default="cn",
        help="Market type: cn (A-share) or us (US stocks)"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Trading date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration file"
    )
    parser.add_argument(
        "--local-db",
        action="store_true",
        help="Use local SQLite database"
    )

    # Pipeline control
    parser.add_argument(
        "--skip-deepear",
        action="store_true",
        help="Skip DeepEar phase (full mode only)"
    )
    parser.add_argument(
        "--skip-deepfund",
        action="store_true",
        help="Skip DeepFund phase (full mode only)"
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue pipeline even if a phase fails"
    )

    # Backtest options
    parser.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated list of tickers for backtest (e.g., '600519,000858')"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date for backtest in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date for backtest in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--cashflow",
        type=float,
        default=100000.0,
        help="Initial capital for backtest (default: 100000)"
    )
    parser.add_argument(
        "--prefetch-only",
        action="store_true",
        help="Only prefetch data without running backtest"
    )
    # LLM-powered backtest options
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Enable LLM-based intelligent trading decisions (requires API keys)"
    )
    parser.add_argument(
        "--analysts",
        type=str,
        default=DEFAULT_BACKTEST_ANALYSTS_ARG,
        help="Comma-separated list of analysts for LLM backtest "
             "(e.g., 'fundamental,technical,company_news'). "
             "Available: fundamental, technical, company_news, insider, macroeconomic, policy, deepear_intelligence"
    )
    parser.add_argument(
        "--personality",
        type=str,
        choices=VALID_PERSONALITIES,
        default="balanced",
        help="Investment personality for LLM backtest (default: balanced)"
    )
    parser.add_argument(
        "--benchmark-mode",
        type=str,
        choices=["auto", "index", "equal_weight", "none"],
        default="auto",
        help="Benchmark mode: auto (index fallback), index, equal_weight, or none"
    )
    parser.add_argument(
        "--benchmark-index",
        type=str,
        help="Benchmark index code (e.g., 000300.SH for CSI 300)"
    )
    # Multi-personality mode options
    parser.add_argument(
        "--personalities",
        type=str,
        default=DEFAULT_MULTI_PERSONALITIES_ARG,
        help="Comma-separated list of personalities for multi-personality mode"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum parallel workers for multi-personality mode (default: auto)"
    )

    # Environment
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Check environment and exit"
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Don't display banner"
    )

    args = parser.parse_args()
    args._market_explicit = any(arg == "--market" or arg.startswith("--market=") for arg in sys.argv[1:])
    args._analysts_explicit = any(arg == "--analysts" or arg.startswith("--analysts=") for arg in sys.argv[1:])
    args._benchmark_mode_explicit = any(arg == "--benchmark-mode" or arg.startswith("--benchmark-mode=") for arg in sys.argv[1:])
    args._benchmark_index_explicit = any(arg == "--benchmark-index" or arg.startswith("--benchmark-index=") for arg in sys.argv[1:])

    # Handle check-env
    if args.check_env:
        if check_env_file():
            print("✅ Environment file exists")
        else:
            print("⚠️  Environment file missing or incomplete")
        return 0

    # Print banner
    if not args.no_banner:
        print_banner()

    # Route to appropriate mode
    if args.mode == "deepear":
        exit_code = run_deepear(args)
    elif args.mode == "deepfund":
        exit_code = run_deepfund(args)
    elif args.mode == "full":
        exit_code = run_full_pipeline(args)
    elif args.mode == "backtest":
        exit_code = run_backtest_mode(args)
    elif args.mode == "multi-personality":
        exit_code = run_multi_personality_mode(args)
    else:
        print("ERROR: Invalid mode. Use deepear, deepfund, full, backtest, or multi-personality.")
        return 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
