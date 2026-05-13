"""Shared provider routing helpers for market-data configuration."""

from __future__ import annotations

import os
from typing import Mapping, Optional


US_DATA_PROVIDER_ALIASES: dict[str, str] = {
    "alpha": "alpha_vantage",
    "alphavantage": "alpha_vantage",
    "alpha_vantage": "alpha_vantage",
    "fmp": "fmp",
    "financialmodelingprep": "fmp",
    "yfinance": "yfinance",
    "yf": "yfinance",
}

CN_DATA_PROVIDER_ALIASES: dict[str, str] = {
    "tushare": "tushare",
}


def normalize_us_data_provider(value: Optional[str]) -> Optional[str]:
    """Normalize a US market-data provider name, returning None for unknown values."""
    key = (value or "").strip().lower()
    return US_DATA_PROVIDER_ALIASES.get(key)


def normalize_cn_data_provider(value: Optional[str]) -> Optional[str]:
    """Normalize a CN market-data provider name, returning None for unknown values."""
    key = (value or "").strip().lower()
    return CN_DATA_PROVIDER_ALIASES.get(key)


def default_us_data_provider(env: Optional[Mapping[str, str]] = None) -> str:
    """Return the default US provider, preferring FMP when its key is configured."""
    env_map = os.environ if env is None else env
    return "fmp" if str(env_map.get("FMP_API_KEY", "")).strip() else "alpha_vantage"


def preferred_us_data_provider(
    *,
    configured: Optional[str] = None,
    env_override: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve a US provider from env override, config, and key-based fallback."""
    override = normalize_us_data_provider(env_override)
    if override:
        return override

    selected = normalize_us_data_provider(configured)
    if selected:
        return selected

    return default_us_data_provider(env)
