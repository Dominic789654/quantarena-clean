"""Tests for backtest adapter API source config builder."""

from backtest.workflow_adapter import BacktestWorkflowAdapter


def _adapter_for_market(market: str) -> BacktestWorkflowAdapter:
    adapter = BacktestWorkflowAdapter.__new__(BacktestWorkflowAdapter)
    adapter.market = market
    return adapter


def test_backtest_us_override_takes_priority(monkeypatch):
    monkeypatch.setenv("DEEPFUND_US_API_SOURCE", "fmp")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha")
    monkeypatch.setenv("FMP_API_KEY", "fmp")

    cfg = _adapter_for_market("us")._build_api_source_config()
    assert cfg["default"] == "fmp"
    assert cfg["us_source"] == "fmp"


def test_backtest_us_defaults_to_fmp_when_fmp_key_exists(monkeypatch):
    monkeypatch.delenv("DEEPFUND_US_API_SOURCE", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setenv("FMP_API_KEY", "fmp")

    cfg = _adapter_for_market("us")._build_api_source_config()
    assert cfg["default"] == "fmp"
    assert cfg["us_source"] == "fmp"


def test_backtest_us_defaults_to_fmp_when_both_keys_exist(monkeypatch):
    monkeypatch.delenv("DEEPFUND_US_API_SOURCE", raising=False)
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha")
    monkeypatch.setenv("FMP_API_KEY", "fmp")

    cfg = _adapter_for_market("us")._build_api_source_config()
    assert cfg["default"] == "fmp"
    assert cfg["us_source"] == "fmp"


def test_backtest_cn_default_is_tushare(monkeypatch):
    monkeypatch.delenv("DEEPFUND_US_API_SOURCE", raising=False)
    monkeypatch.setenv("DEEPFUND_CN_API_SOURCE", "tushare")

    cfg = _adapter_for_market("cn")._build_api_source_config()
    assert cfg["default"] == "tushare"
    assert cfg["cn_source"] == "tushare"


def test_backtest_cn_explicit_invalid_source_is_preserved_for_validator(monkeypatch):
    monkeypatch.setenv("DEEPFUND_CN_API_SOURCE", "alpha_vantage")

    cfg = _adapter_for_market("cn")._build_api_source_config()
    assert cfg["default"] == "alpha_vantage"
    assert cfg["cn_source"] == "alpha_vantage"


def test_backtest_us_explicit_config_is_respected(monkeypatch):
    monkeypatch.delenv("DEEPFUND_US_API_SOURCE", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    cfg = _adapter_for_market("us")._build_api_source_config({"default": "fmp", "us_source": "fmp"})
    assert cfg["default"] == "fmp"
    assert cfg["us_source"] == "fmp"
