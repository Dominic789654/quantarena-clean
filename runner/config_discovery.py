"""DeepFund config discovery helpers extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-config-discovery change (docs/refactor_program_plan.md
Phase 2). run.py re-exports these names so every existing
`run.<name>` monkeypatch string path and `from run import <name>`
import keeps resolving.

`_get_deepfund_config_candidates` and `_select_backtest_config_file`
resolve the project root via `get_project_root()` instead of run.py's
module-level `PROJECT_ROOT` global (which is itself just
`get_project_root()` called once at run.py's import time) since that
global is not in scope once the functions move.
"""

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from shared.config.provider_routing import preferred_us_data_provider
from shared.utils.path_manager import get_project_root


def _get_deepfund_config_candidates(market: Optional[str]) -> List[Path]:
    """Build ordered config candidates for DeepFund auto config selection."""
    config_dir = get_project_root() / "deepfund" / "src" / "config"
    market_key = (market or "").lower()

    if market_key in ["cn", "china", "cn_a", "ashare"]:
        return [
            config_dir / "exp_a_share.yaml",
            config_dir / "ashare.yaml",
        ]

    if market_key in ["us", "usa", "us_stocks"]:
        us_candidates = [
            config_dir / "exp_us_stocks.yaml",
            config_dir / "dev.yaml",
            config_dir / "us.yaml",
        ]

        # Prefer `us.yaml` whenever FMP is available unless the user explicitly forces Alpha.
        provider = preferred_us_data_provider(
            env_override=os.getenv("DEEPFUND_US_API_SOURCE", ""),
        )
        if provider == "fmp":
            return [us_candidates[0], us_candidates[2], us_candidates[1]]

        return us_candidates

    return [config_dir / "dev.yaml"]


def _load_yaml_config_file(config_path: Optional[Path]) -> Dict[str, Any]:
    """Load a YAML config file into a dict."""
    if config_path is None:
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ValueError(f"Configuration file not found: {config_path}")
    except yaml.YAMLError as exc:
        raise ValueError(f"Error parsing configuration file {config_path}: {exc}")
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file must contain a YAML mapping: {config_path}")
    return data


def _select_backtest_config_file(args: argparse.Namespace) -> Optional[Path]:
    """Select an optional backtest config file, preferring FOF template when relevant."""
    if args.config:
        return Path(args.config)

    single_personality = str(getattr(args, "personality", "")).strip().lower()
    multi_personalities_arg = str(getattr(args, "personalities", "")).strip()
    multi_personalities = {
        item.strip().lower()
        for item in multi_personalities_arg.split(",")
        if item.strip()
    }
    if single_personality == "fof" or "fof" in multi_personalities:
        fof_config = get_project_root() / "deepfund" / "src" / "config" / "fof.yaml"
        if fof_config.exists():
            return fof_config
    return None
