#!/usr/bin/env python3
"""
Unified Agent Trading - Main Entry Point
==========================================
Combines DeepEar (intelligence gathering) and DeepFund (trading analysis)
"""

import argparse
import sys

# Fix Tushare's tk.csv issue BEFORE any other imports!
from runner.bootstrap import _fix_tushare_token_file, load_dotenv_file  # noqa: F401

# Apply the fix FIRST, before any other imports
_fix_tushare_token_file()

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()

from runner.runtime_options import DEFAULT_BACKTEST_ANALYSTS_ARG  # noqa: F401,E402
DEFAULT_MULTI_PERSONALITIES_ARG = "conservative,balanced,aggressive,passive"


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

from runner.modes.deepear import run_deepear  # noqa: F401
from runner.modes.deepfund import run_deepfund  # noqa: F401
from runner.modes.pipeline import run_full_pipeline  # noqa: F401


from runner.runtime_options import VALID_PERSONALITIES, _parse_tickers_arg  # noqa: F401


from runner.runtime_options import _parse_optional_csv  # noqa: F401


from runner.cli_support import _print_backtest_mode_config, _print_backtest_result  # noqa: F401


from runner.runtime_options import _parse_personalities_arg  # noqa: F401


from runner.cli_support import (  # noqa: F401
    _print_multi_personality_config,
    _print_multi_personality_results,
)


from runner.modes.backtest import (  # noqa: F401
    _validate_backtest_date_range,
    _execute_backtest_mode,
    run_backtest_mode,
)
from runner.modes.multi_personality import run_multi_personality_mode  # noqa: F401


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
