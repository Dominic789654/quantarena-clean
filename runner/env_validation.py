"""Environment validation helpers extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
add-run-module-shim-and-env-validation change
(docs/refactor_program_plan.md Phase 2, the critical step). run.py
re-exports every name here so existing `run.<name>` monkeypatch string
paths and `from run import <name>` imports keep resolving.

`_validate_backtest_environment_for_runtime` calls `_validate_environment`
internally. Both moved here together, so a plain bare-name call would
resolve against this module's own `_validate_environment` -- silently
ignoring `monkeypatch.setattr("run._validate_environment", ...)`
(reproduced by
tests/test_backtest_fof_config_runtime.py::test_llm_backtest_validation_uses_full_env_validator).
The call is routed through `runner._shim.run_module()` instead, so it
picks up whatever `_validate_environment` currently lives on the public
`run` module (patched or not), falling back to the local definition when
the shim can't find a `run` module attribute (e.g. this module is used
standalone, outside of run.py).

`check_env_file` resolves the project root via `get_project_root()`
instead of run.py's module-level `PROJECT_ROOT` global, mirroring the
substitution already used in `runner/config_discovery.py`.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from shared.config.provider_routing import preferred_us_data_provider
from shared.utils.path_manager import get_project_root

from runner import _shim


def _validate_environment(mode: str = None, verbose: bool = True) -> bool:
    """
    Validate environment variables before running.

    Args:
        mode: Operating mode ('deepear', 'deepfund', 'backtest', or None)
        verbose: Whether to print validation results

    Returns:
        True if validation passes, False otherwise
    """
    try:
        from shared.config.validator import validate_env
        return validate_env(mode=mode, raise_on_error=True, verbose=verbose)
    except ImportError:
        # Validator module not available, skip validation
        return True
    except ValueError as e:
        if verbose:
            print(f"\n{'='*60}", file=sys.stderr)
            print("Environment Configuration Error", file=sys.stderr)
            print('='*60, file=sys.stderr)
            print(f"\n{e}", file=sys.stderr)
            print(f"\n{'='*60}", file=sys.stderr)
            print("Quick Fix:", file=sys.stderr)
            print("  1. cp .env.example .env", file=sys.stderr)
            print("  2. Edit .env and fill in your API keys", file=sys.stderr)
            print("  3. Run again", file=sys.stderr)
            print('='*60 + "\n", file=sys.stderr)
        return False


def _print_backtest_env_error(message: str, verbose: bool = True) -> None:
    """Print a focused backtest environment validation error."""
    if not verbose:
        return
    print(f"\n{'='*60}", file=sys.stderr)
    print("Backtest Environment Configuration Error", file=sys.stderr)
    print('='*60, file=sys.stderr)
    print(f"\n{message}", file=sys.stderr)
    print(f"\n{'='*60}\n", file=sys.stderr)


def _configured_us_data_provider(config: Dict[str, Any]) -> Optional[str]:
    """Return the US data provider configured in the resolved runtime config."""
    api_source = config.get("api_source") or {}
    if not isinstance(api_source, dict):
        return None
    return str(api_source.get("us_source") or api_source.get("default") or "").strip() or None


def _validate_non_llm_backtest_environment(runtime: Dict[str, Any], verbose: bool = True) -> bool:
    """Validate only the data dependency needed by non-LLM backtests."""
    market = str(runtime.get("market") or "").strip().lower()
    config = runtime.get("config") or {}

    if market == "cn":
        explicit_cn_source = os.getenv("DEEPFUND_CN_API_SOURCE", "").strip().lower()
        if explicit_cn_source and explicit_cn_source != "tushare":
            _print_backtest_env_error(
                "DEEPFUND_CN_API_SOURCE supports only 'tushare' for CN backtests.",
                verbose=verbose,
            )
            return False
        if not os.getenv("TUSHARE_API_KEY", "").strip():
            _print_backtest_env_error(
                "Set TUSHARE_API_KEY to run CN backtests that need market data.",
                verbose=verbose,
            )
            return False
        return True

    if market == "us":
        provider = preferred_us_data_provider(
            configured=_configured_us_data_provider(config),
            env_override=os.getenv("DEEPFUND_US_API_SOURCE", ""),
        )
        required_key_by_provider = {
            "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
            "fmp": "FMP_API_KEY",
        }
        required_key = required_key_by_provider.get(provider)
        if required_key is None:
            _print_backtest_env_error(
                f"US backtests currently support FMP or Alpha Vantage market data, got '{provider}'. "
                "Set DEEPFUND_US_API_SOURCE=fmp or DEEPFUND_US_API_SOURCE=alpha_vantage.",
                verbose=verbose,
            )
            return False
        if required_key and not os.getenv(required_key, "").strip():
            _print_backtest_env_error(
                f"Set {required_key} to run US backtests with the '{provider}' data provider. "
                "Set DEEPFUND_US_API_SOURCE=fmp or DEEPFUND_US_API_SOURCE=alpha_vantage to choose a provider.",
                verbose=verbose,
            )
            return False
        return True

    _print_backtest_env_error(
        f"Unsupported backtest market '{market}'. Expected 'cn' or 'us'.",
        verbose=verbose,
    )
    return False


def _validate_backtest_environment_for_runtime(runtime: Dict[str, Any], verbose: bool = True) -> bool:
    """Validate backtest environment requirements after resolving runtime mode."""
    if runtime.get("use_llm"):
        # Route through the public `run` module (or __main__) so that
        # monkeypatch.setattr("run._validate_environment", ...) is honored
        # even though this function now lives in runner/, not run.py.
        validate_environment = getattr(_shim.run_module(), "_validate_environment", None) or _validate_environment
        return validate_environment(mode="backtest", verbose=verbose)
    return _validate_non_llm_backtest_environment(runtime, verbose=verbose)


def check_env_file() -> bool:
    """Check if .env file exists, create from example if not."""
    project_root = get_project_root()
    env_file: Path = project_root / ".env"
    env_example: Path = project_root / ".env.example"

    if env_file.exists():
        return True

    if env_example.exists():
        print("WARNING: .env file not found. Creating from .env.example...")
        import shutil
        shutil.copy(env_example, env_file)
        print(f"Created .env file at {env_file}")
        print("Please edit .env file with your API keys before running again.")
        return False
    else:
        print("ERROR: Neither .env nor .env.example found!")
        return False
