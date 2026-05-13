"""Tests for DeepFund default config candidate selection."""

from run import VALID_PERSONALITIES, _get_deepfund_config_candidates


def _candidate_names(market: str):
    return [path.name for path in _get_deepfund_config_candidates(market)]


def test_us_candidates_prefer_fmp_template_when_fmp_key_exists(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPFUND_US_API_SOURCE", raising=False)

    assert _candidate_names("us") == ["exp_us_stocks.yaml", "us.yaml", "dev.yaml"]


def test_us_candidates_prefer_fmp_template_when_both_keys_exist(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test")
    monkeypatch.delenv("DEEPFUND_US_API_SOURCE", raising=False)

    assert _candidate_names("us") == ["exp_us_stocks.yaml", "us.yaml", "dev.yaml"]


def test_us_candidates_honor_explicit_fmp_source(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test")
    monkeypatch.setenv("DEEPFUND_US_API_SOURCE", "fmp")

    assert _candidate_names("us") == ["exp_us_stocks.yaml", "us.yaml", "dev.yaml"]


def test_us_candidates_honor_explicit_alpha_source(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setenv("DEEPFUND_US_API_SOURCE", "alpha_vantage")

    assert _candidate_names("us") == ["exp_us_stocks.yaml", "dev.yaml", "us.yaml"]


def test_cn_candidates_are_stable(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPFUND_US_API_SOURCE", raising=False)

    assert _candidate_names("cn") == ["exp_a_share.yaml", "ashare.yaml"]


def test_valid_personalities_include_new_paradigm_scaffold_entries():
    assert "macro_tactical" in VALID_PERSONALITIES
    assert "tactical_allocation" in VALID_PERSONALITIES
    assert "fundamental_value" in VALID_PERSONALITIES
    assert "value" in VALID_PERSONALITIES
    assert "behavioral_momentum" in VALID_PERSONALITIES
    assert "momentum" in VALID_PERSONALITIES
