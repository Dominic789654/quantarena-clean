"""Backtest / multi-personality runtime option resolution extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-runtime-options change (docs/refactor_program_plan.md
Phase 2). run.py re-exports every name here so existing `run.<name>`
monkeypatch string paths and `from run import <name>` imports keep
resolving.

`DEFAULT_BACKTEST_ANALYSTS_ARG` and `VALID_PERSONALITIES` moved along
with the resolvers/helpers because those functions reference them by
bare name internally; leaving the constants behind in run.py would make
the bare-name lookups fail with `NameError` once the referencing
functions live in this module's own global namespace. `run.py`
re-exports both constants so its own (unmoved) argparse setup in
`main()` keeps working unchanged.

`_parse_tickers_arg`, `_parse_optional_csv`, `_parse_personalities_arg`,
`_extract_market_from_config`, and `_extract_tickers_from_config` moved
too: each is a private helper called only by the two resolvers below
(verified by grep — see the change's proposal.md monkeypatch audit).
"""

import argparse
from typing import Any, Dict, List, Optional

from shared.config.profile_registry import VALID_PROFILE_NAMES

from runner.config_discovery import _load_yaml_config_file, _select_backtest_config_file

DEFAULT_BACKTEST_ANALYSTS_ARG = "fundamental,technical,company_news"

VALID_PERSONALITIES = list(VALID_PROFILE_NAMES)


def _extract_market_from_config(config: Dict[str, Any]) -> Optional[str]:
    """Extract market from flat or nested trading config."""
    market = str(config.get("market", "")).strip()
    if market:
        return market.lower()

    trading_cfg = config.get("trading") or {}
    if isinstance(trading_cfg, dict):
        nested_market = str(trading_cfg.get("market", "")).strip()
        if nested_market:
            return nested_market.lower()

    return None


def _extract_tickers_from_config(config: Dict[str, Any]) -> List[str]:
    """Extract tickers from either a flat list or an experiment universe definition."""
    raw_tickers = config.get("tickers") or []
    tickers = [str(ticker).strip() for ticker in raw_tickers if str(ticker).strip()]
    if tickers:
        return tickers

    experiment_universe = config.get("experiment_universe") or config.get("universe") or {}
    sectors = experiment_universe.get("sectors") if isinstance(experiment_universe, dict) else []
    collected: List[str] = []
    seen = set()
    for sector in sectors or []:
        stocks = (sector or {}).get("stocks") or []
        for stock in stocks:
            if isinstance(stock, dict):
                ticker = str(stock.get("ticker", "")).strip()
            else:
                ticker = str(stock).strip()
            if ticker and ticker not in seen:
                seen.add(ticker)
                collected.append(ticker)
    return collected


def _parse_tickers_arg(tickers_arg: Optional[str], mode_name: str) -> Optional[List[str]]:
    """Parse comma-separated tickers from CLI args."""
    if not tickers_arg:
        print(f"ERROR: --tickers is required for {mode_name}")
        print("Example: --tickers '600519,000858,300750'")
        return None
    tickers = [t.strip() for t in tickers_arg.split(",") if t.strip()]
    if not tickers:
        print("ERROR: No valid tickers provided")
        return None
    print(f"Tickers: {tickers}")
    return tickers


def _parse_optional_csv(arg_value: Optional[str]) -> Optional[List[str]]:
    """Parse optional comma-separated list."""
    if not arg_value:
        return None
    items = [item.strip() for item in arg_value.split(",") if item.strip()]
    return items or None


def _parse_personalities_arg(personalities_arg: str) -> Optional[List[str]]:
    """Parse and validate personalities."""
    personalities = [p.strip() for p in personalities_arg.split(",") if p.strip()]
    for personality in personalities:
        if personality not in VALID_PERSONALITIES:
            print(f"ERROR: Invalid personality '{personality}'. Valid options: {VALID_PERSONALITIES}")
            return None
    return personalities


def _resolve_backtest_runtime_options(args: argparse.Namespace) -> Dict[str, Any]:
    """Resolve backtest runtime options from CLI args plus optional YAML config."""
    config_path = _select_backtest_config_file(args)
    config = _load_yaml_config_file(config_path)

    tickers_arg = args.tickers
    config_tickers = _extract_tickers_from_config(config)
    if not tickers_arg and config_tickers:
        tickers_arg = ",".join(config_tickers)
    tickers = _parse_tickers_arg(tickers_arg, mode_name="backtest mode")
    if tickers is None:
        raise ValueError("tickers are required for backtest mode")

    config_analysts = config.get("workflow_analysts") or config.get("analysts") or []
    analysts_arg = args.analysts
    analysts_explicit = bool(getattr(args, "_analysts_explicit", False))
    if (not analysts_explicit) and (not analysts_arg or analysts_arg == DEFAULT_BACKTEST_ANALYSTS_ARG) and config_analysts:
        analysts = [str(item).strip() for item in config_analysts if str(item).strip()]
    else:
        analysts = _parse_optional_csv(analysts_arg)

    personality = args.personality
    if personality == "balanced" and config.get("personality"):
        personality = str(config.get("personality")).strip().lower()

    market = args.market
    config_market = _extract_market_from_config(config)
    market_explicit = bool(getattr(args, "_market_explicit", False))
    if not market_explicit and config_market:
        market = config_market

    cashflow = args.cashflow
    if cashflow == 100000.0 and config.get("cashflow") is not None:
        cashflow = float(config.get("cashflow"))

    use_llm = bool(args.use_llm)
    if not use_llm:
        use_llm = bool(config.get("llm")) or bool(config_analysts) or personality == "fof"

    resolved_config = dict(config)
    resolved_config["tickers"] = list(tickers)
    resolved_config["workflow_analysts"] = list(analysts or [])
    resolved_config["personality"] = personality
    resolved_config["market"] = market
    resolved_config["cashflow"] = cashflow

    trading_cfg = dict(resolved_config.get("trading", {}) or {})
    trading_cfg["market"] = market.upper()
    resolved_config["trading"] = trading_cfg

    benchmark_cfg = dict(resolved_config.get("benchmark", {}) or {})
    benchmark_mode_explicit = bool(getattr(args, "_benchmark_mode_explicit", False))
    benchmark_index_explicit = bool(getattr(args, "_benchmark_index_explicit", False))
    if benchmark_mode_explicit:
        benchmark_cfg["mode"] = args.benchmark_mode
    elif not benchmark_cfg.get("mode"):
        benchmark_cfg["mode"] = args.benchmark_mode
    if benchmark_index_explicit and args.benchmark_index:
        benchmark_cfg["index_code"] = args.benchmark_index
    resolved_config["benchmark"] = benchmark_cfg

    return {
        "tickers": tickers,
        "analysts": analysts,
        "personality": personality,
        "market": market,
        "cashflow": cashflow,
        "use_llm": use_llm,
        "config": resolved_config,
        "config_path": str(config_path) if config_path else None,
    }


def _resolve_multi_personality_runtime_options(args: argparse.Namespace) -> Dict[str, Any]:
    """Resolve multi-personality runtime options from CLI args plus optional YAML config."""
    config_path = _select_backtest_config_file(args)
    config = _load_yaml_config_file(config_path)

    tickers_arg = args.tickers
    config_tickers = _extract_tickers_from_config(config)
    if not tickers_arg and config_tickers:
        tickers_arg = ",".join(config_tickers)
    tickers = _parse_tickers_arg(tickers_arg, mode_name="multi-personality mode")
    if tickers is None:
        raise ValueError("tickers are required for multi-personality mode")

    config_analysts = config.get("workflow_analysts") or config.get("analysts") or []
    analysts_arg = args.analysts
    analysts_explicit = bool(getattr(args, "_analysts_explicit", False))
    if (not analysts_explicit) and (not analysts_arg or analysts_arg == DEFAULT_BACKTEST_ANALYSTS_ARG) and config_analysts:
        analysts = [str(item).strip() for item in config_analysts if str(item).strip()]
    else:
        analysts = _parse_optional_csv(analysts_arg)

    personalities = _parse_personalities_arg(args.personalities)
    if personalities is None:
        raise ValueError("invalid personalities for multi-personality mode")

    market = args.market
    config_market = _extract_market_from_config(config)
    market_explicit = bool(getattr(args, "_market_explicit", False))
    if not market_explicit and config_market:
        market = config_market

    cashflow = args.cashflow
    if cashflow == 100000.0 and config.get("cashflow") is not None:
        cashflow = float(config.get("cashflow"))

    use_llm = True

    resolved_config = dict(config)
    resolved_config["tickers"] = list(tickers)
    resolved_config["workflow_analysts"] = list(analysts or [])
    resolved_config["personalities"] = list(personalities)
    resolved_config["market"] = market
    resolved_config["cashflow"] = cashflow

    trading_cfg = dict(resolved_config.get("trading", {}) or {})
    trading_cfg["market"] = market.upper()
    resolved_config["trading"] = trading_cfg

    benchmark_cfg = dict(resolved_config.get("benchmark", {}) or {})
    benchmark_mode_explicit = bool(getattr(args, "_benchmark_mode_explicit", False))
    benchmark_index_explicit = bool(getattr(args, "_benchmark_index_explicit", False))
    if benchmark_mode_explicit:
        benchmark_cfg["mode"] = args.benchmark_mode
    elif not benchmark_cfg.get("mode"):
        benchmark_cfg["mode"] = args.benchmark_mode
    if benchmark_index_explicit and args.benchmark_index:
        benchmark_cfg["index_code"] = args.benchmark_index
    resolved_config["benchmark"] = benchmark_cfg

    return {
        "tickers": tickers,
        "analysts": analysts,
        "personalities": personalities,
        "market": market,
        "cashflow": cashflow,
        "use_llm": use_llm,
        "config": resolved_config,
        "config_path": str(config_path) if config_path else None,
    }
