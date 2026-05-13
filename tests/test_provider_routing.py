"""Tests for shared market-data provider routing helpers."""

from shared.config.provider_routing import (
    default_us_data_provider,
    normalize_cn_data_provider,
    normalize_us_data_provider,
    preferred_us_data_provider,
)


def test_normalize_us_data_provider_aliases():
    assert normalize_us_data_provider("alpha") == "alpha_vantage"
    assert normalize_us_data_provider("AlphaVantage") == "alpha_vantage"
    assert normalize_us_data_provider("financialmodelingprep") == "fmp"
    assert normalize_us_data_provider("yf") == "yfinance"
    assert normalize_us_data_provider("unknown") is None


def test_normalize_cn_data_provider_accepts_only_tushare():
    assert normalize_cn_data_provider("tushare") == "tushare"
    assert normalize_cn_data_provider("fmp") is None


def test_default_us_data_provider_prefers_fmp_key():
    assert default_us_data_provider({"FMP_API_KEY": "key"}) == "fmp"
    assert default_us_data_provider({"FMP_API_KEY": ""}) == "alpha_vantage"
    assert default_us_data_provider({}) == "alpha_vantage"


def test_preferred_us_data_provider_honors_override_then_config_then_fallback():
    assert preferred_us_data_provider(env_override="fmp", configured="alpha") == "fmp"
    assert preferred_us_data_provider(env_override="alpha", configured="fmp") == "alpha_vantage"
    assert preferred_us_data_provider(configured="yf") == "yfinance"
    assert preferred_us_data_provider(configured="unknown", env={"FMP_API_KEY": "key"}) == "fmp"
