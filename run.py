#!/usr/bin/env python3
"""
Unified Agent Trading - Main Entry Point
==========================================
Combines DeepEar (intelligence gathering) and DeepFund (trading analysis)
"""

import sys

# Fix Tushare's tk.csv issue BEFORE any other imports!
from runner.bootstrap import _fix_tushare_token_file, load_dotenv_file  # noqa: F401

# Apply the fix FIRST, before any other imports
_fix_tushare_token_file()

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()

# Re-export block: every name below used to be defined directly in this
# file. run.py now only re-exports them, so existing `run.<name>`
# monkeypatch string paths and `from run import <name>` imports keep
# resolving while the implementations live in runner/ (see
# docs/refactor_program_plan.md Phase 2 and runner/__init__.py).

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
    DEFAULT_BACKTEST_ANALYSTS_ARG,
    VALID_PERSONALITIES,
    _extract_market_from_config,
    _extract_tickers_from_config,
    _parse_tickers_arg,
    _parse_optional_csv,
    _parse_personalities_arg,
    _resolve_backtest_runtime_options,
    _resolve_multi_personality_runtime_options,
)

from runner.cli_support import (  # noqa: F401
    print_banner,
    _print_backtest_mode_config,
    _print_backtest_result,
    _print_multi_personality_config,
    _print_multi_personality_results,
)

from runner.modes.deepear import run_deepear  # noqa: F401
from runner.modes.deepfund import run_deepfund  # noqa: F401
from runner.modes.pipeline import run_full_pipeline  # noqa: F401
from runner.modes.backtest import (  # noqa: F401
    _validate_backtest_date_range,
    _execute_backtest_mode,
    run_backtest_mode,
)
from runner.modes.multi_personality import run_multi_personality_mode  # noqa: F401

from runner.cli import DEFAULT_MULTI_PERSONALITIES_ARG, main  # noqa: F401


if __name__ == "__main__":
    sys.exit(main())
