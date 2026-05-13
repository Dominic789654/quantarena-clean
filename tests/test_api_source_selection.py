"""Tests for API source resolution logic."""

import sys
import types

# `apis` package imports yfinance at module import time. Stub it for unit tests.
if "yfinance" not in sys.modules:
    sys.modules["yfinance"] = types.SimpleNamespace(Search=object)

from apis.router import APISource, resolve_api_source


def test_resolve_cn_defaults_to_tushare():
    assert resolve_api_source("cn", {}) == APISource.TUSHARE


def test_resolve_us_respects_default_config():
    assert resolve_api_source("us", {"default": "fmp"}) == APISource.FMP


def test_resolve_us_prefers_us_source_over_default():
    cfg = {"default": "fmp", "us_source": "alpha_vantage"}
    assert resolve_api_source("us", cfg) == APISource.ALPHA_VANTAGE


def test_resolve_invalid_source_falls_back_by_market(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    assert resolve_api_source("us", {"default": "unknown"}) == APISource.ALPHA_VANTAGE
    assert resolve_api_source("cn", {"default": "unknown"}) == APISource.TUSHARE


def test_resolve_us_env_fallback_prefers_fmp_when_fmp_key_exists(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    assert resolve_api_source("us", {}) == APISource.FMP


def test_resolve_us_env_fallback_prefers_fmp_when_both_keys_exist(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test")
    assert resolve_api_source("us", {}) == APISource.FMP


def test_resolve_cn_invalid_source_falls_back_to_tushare():
    assert resolve_api_source("cn", {"cn_source": "alpha_vantage"}) == APISource.TUSHARE


def test_resolve_cn_invalid_default_falls_back_to_tushare():
    assert resolve_api_source("cn", {"default": "fmp"}) == APISource.TUSHARE


def test_resolve_us_rejects_cn_only_source_and_falls_back_to_fmp(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.delenv("DEEPFUND_US_API_SOURCE", raising=False)
    assert resolve_api_source("us", {"default": "tushare"}) == APISource.FMP
