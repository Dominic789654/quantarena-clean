"""Tests for backtest runtime config resolution with FOF support."""

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
from types import SimpleNamespace

from run import (
    DEFAULT_BACKTEST_ANALYSTS_ARG,
    DEFAULT_MULTI_PERSONALITIES_ARG,
    _execute_backtest_mode,
    main,
    _validate_backtest_environment_for_runtime,
    _resolve_backtest_runtime_options,
    _resolve_multi_personality_runtime_options,
    _select_backtest_config_file,
    run_multi_personality_mode,
)


def _make_args(**overrides):
    base = dict(
        tickers=None,
        start_date="2024-01-01",
        end_date="2024-01-31",
        cashflow=100000.0,
        market="cn",
        prefetch_only=False,
        use_llm=False,
        analysts=DEFAULT_BACKTEST_ANALYSTS_ARG,
        personality="balanced",
        personalities=DEFAULT_MULTI_PERSONALITIES_ARG,
        max_workers=None,
        benchmark_mode="auto",
        benchmark_index=None,
        config=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)




def test_main_marks_benchmark_cli_flags_explicit(monkeypatch):
    captured = {}

    def _fake_run_backtest_mode(args):
        captured["benchmark_mode_explicit"] = getattr(args, "_benchmark_mode_explicit", False)
        captured["benchmark_index_explicit"] = getattr(args, "_benchmark_index_explicit", False)
        captured["benchmark_mode"] = args.benchmark_mode
        captured["benchmark_index"] = args.benchmark_index
        return 0

    monkeypatch.setattr("run.run_backtest_mode", _fake_run_backtest_mode)
    monkeypatch.setattr("run.print_banner", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run.py",
            "--mode",
            "backtest",
            "--tickers",
            "MSFT",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-02",
            "--benchmark-mode",
            "index",
            "--benchmark-index",
            "SPY",
            "--no-banner",
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert captured["benchmark_mode_explicit"] is True
    assert captured["benchmark_index_explicit"] is True
    assert captured["benchmark_mode"] == "index"
    assert captured["benchmark_index"] == "SPY"


def test_select_backtest_config_file_prefers_default_fof_template():
    args = _make_args(personality="fof", config=None)
    config_path = _select_backtest_config_file(args)

    assert config_path is not None
    assert config_path.name == "fof.yaml"


def test_resolve_backtest_runtime_options_extracts_tickers_from_experiment_universe(tmp_path: Path):
    config_path = tmp_path / "ashare_universe.yaml"
    config_path.write_text(
        """
market: cn
cashflow: 120000
workflow_analysts:
  - fundamental
experiment_universe:
  name: ashare_5x4
  sectors:
    - name: financials
      stocks:
        - ticker: "600036"
          bucket: large_value
        - ticker: "601166"
          bucket: large_growth
    - name: consumer
      stocks:
        - ticker: "600519"
          bucket: large_value
        - ticker: "000858"
          bucket: large_growth
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(config=str(config_path), tickers=None, analysts=DEFAULT_BACKTEST_ANALYSTS_ARG)
    runtime = _resolve_backtest_runtime_options(args)

    assert runtime["tickers"] == ["600036", "601166", "600519", "000858"]
    assert runtime["config"]["tickers"] == ["600036", "601166", "600519", "000858"]
    assert runtime["market"] == "cn"


def test_resolve_backtest_runtime_options_uses_yaml_fof_settings(tmp_path: Path):
    config_path = tmp_path / "fof_runtime.yaml"
    config_path.write_text(
        """
personality: fof
market: us
cashflow: 250000
workflow_analysts:
  - fundamental
  - insider
llm:
  provider: YiZhan
  model: deepseek-v3.2
tickers:
  - MSFT
  - NVDA
fof:
  sleeves:
    - personality: balanced
      weight: 0.6
    - personality: passive
      weight: 0.4
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(config=str(config_path), tickers=None, analysts=DEFAULT_BACKTEST_ANALYSTS_ARG)
    runtime = _resolve_backtest_runtime_options(args)

    assert runtime["tickers"] == ["MSFT", "NVDA"]
    assert runtime["personality"] == "fof"
    assert runtime["market"] == "us"
    assert runtime["cashflow"] == 250000.0
    assert runtime["analysts"] == ["fundamental", "insider"]
    assert runtime["use_llm"] is True
    assert runtime["config"]["fof"]["sleeves"][0]["personality"] == "balanced"
    assert runtime["config_path"] == str(config_path)


def test_resolve_backtest_runtime_options_preserves_yaml_benchmark_settings(tmp_path: Path):
    config_path = tmp_path / "benchmark_runtime.yaml"
    config_path.write_text(
        """
market: us
cashflow: 250000
workflow_analysts:
  - fundamental
tickers:
  - MSFT
benchmark:
  mode: index
  index_code: SPY
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(config=str(config_path), tickers=None)
    runtime = _resolve_backtest_runtime_options(args)

    assert runtime["config"]["benchmark"]["mode"] == "index"
    assert runtime["config"]["benchmark"]["index_code"] == "SPY"


def test_resolve_backtest_runtime_options_overrides_benchmark_when_cli_explicit(tmp_path: Path):
    config_path = tmp_path / "benchmark_runtime_override.yaml"
    config_path.write_text(
        """
market: us
cashflow: 250000
workflow_analysts:
  - fundamental
tickers:
  - MSFT
benchmark:
  mode: index
  index_code: SPY
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(
        config=str(config_path),
        tickers=None,
        benchmark_mode="equal_weight",
        benchmark_index="QQQ",
        _benchmark_mode_explicit=True,
        _benchmark_index_explicit=True,
    )
    runtime = _resolve_backtest_runtime_options(args)

    assert runtime["config"]["benchmark"]["mode"] == "equal_weight"
    assert runtime["config"]["benchmark"]["index_code"] == "QQQ"


def test_execute_backtest_mode_supports_experiment_universe_config(monkeypatch):
    config_path = PROJECT_ROOT / "deepfund" / "src" / "config" / "ashare_experiment_universe.yaml"
    captured = {}

    def _fake_run_backtest(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(run_id="test", metrics={}, errors=[])

    monkeypatch.setattr("run._print_backtest_result", lambda result: 0)
    monkeypatch.setattr("run._validate_backtest_environment_for_runtime", lambda runtime: True)

    args = _make_args(
        config=str(config_path),
        tickers=None,
        analysts=DEFAULT_BACKTEST_ANALYSTS_ARG,
        market="cn",
    )

    exit_code = _execute_backtest_mode(args, _fake_run_backtest)

    assert exit_code == 0
    assert len(captured["tickers"]) == 20
    assert captured["tickers"][0] == "600036"
    assert captured["tickers"][-1] == "002353"
    assert captured["config"]["experiment_universe"]["name"] == "ashare_5x4_style_matrix"
    assert captured["config"]["market"] == "cn"


def test_non_llm_backtest_validation_does_not_require_llm_env(monkeypatch):
    runtime = {
        "use_llm": False,
        "market": "cn",
        "config": {},
    }
    monkeypatch.delenv("REASONING_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("REASONING_MODEL_ID", raising=False)
    monkeypatch.setenv("TUSHARE_API_KEY", "test-tushare-key")

    assert _validate_backtest_environment_for_runtime(runtime, verbose=False) is True


def test_non_llm_us_backtest_validation_rejects_yfinance_for_backtests(monkeypatch):
    runtime = {
        "use_llm": False,
        "market": "us",
        "config": {},
    }
    monkeypatch.delenv("REASONING_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("REASONING_MODEL_ID", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("DEEPFUND_US_API_SOURCE", "yfinance")

    assert _validate_backtest_environment_for_runtime(runtime, verbose=False) is False


def test_non_llm_us_backtest_validation_requires_selected_provider_key(monkeypatch):
    runtime = {
        "use_llm": False,
        "market": "us",
        "config": {},
    }
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("DEEPFUND_US_API_SOURCE", "fmp")

    assert _validate_backtest_environment_for_runtime(runtime, verbose=False) is False


def test_non_llm_us_backtest_validation_accepts_fmp_key(monkeypatch):
    runtime = {
        "use_llm": False,
        "market": "us",
        "config": {},
    }
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setenv("FMP_API_KEY", "test-fmp-key")
    monkeypatch.setenv("DEEPFUND_US_API_SOURCE", "fmp")

    assert _validate_backtest_environment_for_runtime(runtime, verbose=False) is True


def test_llm_backtest_validation_uses_full_env_validator(monkeypatch):
    calls = []
    runtime = {
        "use_llm": True,
        "market": "cn",
        "config": {},
    }

    def _fake_validate_environment(mode=None, verbose=True):
        calls.append((mode, verbose))
        return True

    monkeypatch.setattr("run._validate_environment", _fake_validate_environment)

    assert _validate_backtest_environment_for_runtime(runtime, verbose=False) is True
    assert calls == [("backtest", False)]


def test_run_multi_personality_mode_validates_after_runtime_resolution(monkeypatch, tmp_path: Path):
    import backtest.multi_personality_engine as mp_engine

    config_path = tmp_path / "multi_env_runtime.yaml"
    config_path.write_text(
        """
market: us
tickers:
  - MSFT
  - NVDA
""".strip(),
        encoding="utf-8",
    )

    calls = []

    def _fake_runtime_validator(runtime, verbose=True):
        calls.append(runtime)
        return False

    monkeypatch.setattr("run._validate_backtest_date_range", lambda *args, **kwargs: True)
    monkeypatch.setattr("run._validate_backtest_environment_for_runtime", _fake_runtime_validator)
    monkeypatch.setattr(mp_engine, "run_multi_personality_backtest", lambda **kwargs: None)

    args = _make_args(config=str(config_path), tickers=None, personalities="balanced")

    exit_code = run_multi_personality_mode(args)

    assert exit_code == 1
    assert calls
    assert calls[0]["tickers"] == ["MSFT", "NVDA"]
    assert calls[0]["use_llm"] is True


def test_resolve_multi_personality_runtime_options_overrides_benchmark_when_cli_explicit(tmp_path: Path):
    config_path = tmp_path / "multi_benchmark_runtime_override.yaml"
    config_path.write_text(
        """
market: us
cashflow: 250000
workflow_analysts:
  - fundamental
tickers:
  - MSFT
benchmark:
  mode: index
  index_code: SPY
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(
        config=str(config_path),
        tickers=None,
        benchmark_mode="equal_weight",
        benchmark_index="QQQ",
        _benchmark_mode_explicit=True,
        _benchmark_index_explicit=True,
    )
    runtime = _resolve_multi_personality_runtime_options(args)

    assert runtime["config"]["benchmark"]["mode"] == "equal_weight"
    assert runtime["config"]["benchmark"]["index_code"] == "QQQ"


def test_execute_backtest_mode_passes_resolved_fof_runtime(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "fof_exec.yaml"
    config_path.write_text(
        """
personality: fof
cashflow: 150000
workflow_analysts:
  - technical
tickers:
  - 600519
  - 000858
fof:
  sleeves:
    - personality: balanced
      weight: 0.7
    - personality: passive
      weight: 0.3
""".strip(),
        encoding="utf-8",
    )

    captured = {}

    def _fake_run_backtest(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(run_id="test", metrics={}, errors=[])

    monkeypatch.setattr("run._print_backtest_result", lambda result: 0)
    monkeypatch.setattr("run._validate_backtest_environment_for_runtime", lambda runtime: True)

    args = _make_args(
        config=str(config_path),
        tickers=None,
        personality="balanced",
        use_llm=False,
        analysts=DEFAULT_BACKTEST_ANALYSTS_ARG,
    )

    exit_code = _execute_backtest_mode(args, _fake_run_backtest)

    assert exit_code == 0
    assert captured["tickers"] == ["600519", "000858"]
    assert captured["personality"] == "fof"
    assert captured["initial_cash"] == 150000.0
    assert captured["use_llm"] is True
    assert captured["analysts"] == ["technical"]
    assert captured["config"]["benchmark"]["mode"] == "auto"
    assert captured["config"]["fof"]["sleeves"][0]["personality"] == "balanced"


def test_resolve_backtest_runtime_options_uses_nested_trading_market(tmp_path: Path):
    config_path = tmp_path / "fof_runtime_nested_market.yaml"
    config_path.write_text(
        """
personality: fof
cashflow: 180000
workflow_analysts:
  - fundamental
llm:
  provider: YiZhan
  model: deepseek-v3.2
api_source:
  default: fmp
  us_source: fmp
trading:
  market: US
tickers:
  - MSFT
  - NVDA
fof:
  sleeves:
    - personality: balanced
      weight: 0.5
    - personality: passive
      weight: 0.5
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(config=str(config_path), tickers=None, market="cn")
    runtime = _resolve_backtest_runtime_options(args)

    assert runtime["market"] == "us"
    assert runtime["config"]["api_source"]["us_source"] == "fmp"
    assert runtime["config"]["trading"]["market"] == "US"


def test_resolve_backtest_runtime_options_overrides_config_metadata_with_cli_tickers(tmp_path: Path):
    config_path = tmp_path / "fof_runtime_cli_override.yaml"
    config_path.write_text(
        """
personality: fof
market: us
cashflow: 250000
workflow_analysts:
  - fundamental
tickers:
  - MSFT
  - NVDA
fof:
  sleeves:
    - personality: balanced
      weight: 0.6
    - personality: passive
      weight: 0.4
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(
        config=str(config_path),
        tickers="AAPL,GOOGL,AMZN",
        analysts="fundamental",
    )
    runtime = _resolve_backtest_runtime_options(args)

    assert runtime["tickers"] == ["AAPL", "GOOGL", "AMZN"]
    assert runtime["config"]["tickers"] == ["AAPL", "GOOGL", "AMZN"]
    assert runtime["config"]["workflow_analysts"] == ["fundamental"]
    assert runtime["config"]["personality"] == "fof"
    assert runtime["config"]["market"] == "us"
    assert runtime["config"]["cashflow"] == 250000.0


def test_resolve_backtest_runtime_options_honors_explicit_cli_market(tmp_path: Path):
    config_path = tmp_path / "fof_runtime_explicit_cli_market.yaml"
    config_path.write_text(
        """
personality: fof
market: us
trading:
  market: US
tickers:
  - MSFT
  - NVDA
fof:
  sleeves:
    - personality: balanced
      weight: 0.6
    - personality: passive
      weight: 0.4
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(config=str(config_path), tickers=None, market="cn", _market_explicit=True)
    runtime = _resolve_backtest_runtime_options(args)

    assert runtime["market"] == "cn"
    assert runtime["config"]["market"] == "cn"
    assert runtime["config"]["trading"]["market"] == "CN"


def test_resolve_backtest_runtime_options_honors_explicit_cli_analysts(tmp_path: Path):
    config_path = tmp_path / "fof_runtime_explicit_cli_analysts.yaml"
    config_path.write_text(
        """
personality: fof
market: us
workflow_analysts:
  - fundamental
  - technical
  - company_news
  - insider
tickers:
  - MSFT
  - NVDA
fof:
  sleeves:
    - personality: balanced
      weight: 0.6
    - personality: passive
      weight: 0.4
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(
        config=str(config_path),
        tickers=None,
        analysts=DEFAULT_BACKTEST_ANALYSTS_ARG,
        _analysts_explicit=True,
    )
    runtime = _resolve_backtest_runtime_options(args)

    assert runtime["analysts"] == ["fundamental", "technical", "company_news"]
    assert runtime["config"]["workflow_analysts"] == ["fundamental", "technical", "company_news"]


def test_select_backtest_config_file_prefers_default_fof_template_for_multi_personality():
    args = _make_args(personalities="balanced,fof", config=None)
    config_path = _select_backtest_config_file(args)

    assert config_path is not None
    assert config_path.name == "fof.yaml"


def test_resolve_multi_personality_runtime_options_uses_yaml_fof_settings(tmp_path: Path):
    config_path = tmp_path / "multi_fof_runtime.yaml"
    config_path.write_text(
        """
market: us
cashflow: 250000
workflow_analysts:
  - fundamental
llm:
  provider: Ark
  model: deepseek-v3.2
api_source:
  default: fmp
  us_source: fmp
trading:
  market: US
tickers:
  - MSFT
  - NVDA
fof:
  sleeves:
    - personality: balanced
      weight: 0.6
    - personality: passive
      weight: 0.4
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(
        config=str(config_path),
        tickers=None,
        personalities="fof,balanced",
        analysts=DEFAULT_BACKTEST_ANALYSTS_ARG,
        market="cn",
    )
    runtime = _resolve_multi_personality_runtime_options(args)

    assert runtime["tickers"] == ["MSFT", "NVDA"]
    assert runtime["personalities"] == ["fof", "balanced"]
    assert runtime["market"] == "us"
    assert runtime["cashflow"] == 250000.0
    assert runtime["analysts"] == ["fundamental"]
    assert runtime["use_llm"] is True
    assert runtime["config"]["api_source"]["us_source"] == "fmp"
    assert runtime["config"]["llm"]["provider"] == "Ark"
    assert runtime["config"]["trading"]["market"] == "US"


def test_resolve_multi_personality_runtime_options_honors_explicit_cli_analysts(tmp_path: Path):
    config_path = tmp_path / "multi_fof_explicit_cli_analysts.yaml"
    config_path.write_text(
        """
market: us
workflow_analysts:
  - fundamental
  - technical
  - company_news
  - insider
tickers:
  - MSFT
  - NVDA
fof:
  sleeves:
    - personality: balanced
      weight: 0.6
    - personality: passive
      weight: 0.4
""".strip(),
        encoding="utf-8",
    )

    args = _make_args(
        config=str(config_path),
        tickers=None,
        personalities="fof,balanced",
        analysts=DEFAULT_BACKTEST_ANALYSTS_ARG,
        _analysts_explicit=True,
    )
    runtime = _resolve_multi_personality_runtime_options(args)

    assert runtime["analysts"] == ["fundamental", "technical", "company_news"]
    assert runtime["config"]["workflow_analysts"] == ["fundamental", "technical", "company_news"]


def test_run_multi_personality_mode_passes_resolved_fof_runtime(monkeypatch, tmp_path: Path):
    import backtest.multi_personality_engine as mp_engine

    config_path = tmp_path / "multi_fof_exec.yaml"
    config_path.write_text(
        """
market: us
cashflow: 180000
workflow_analysts:
  - fundamental
llm:
  provider: Ark
  model: deepseek-v3.2
api_source:
  default: fmp
  us_source: fmp
trading:
  market: US
tickers:
  - MSFT
  - NVDA
fof:
  sleeves:
    - personality: balanced
      weight: 0.5
    - personality: passive
      weight: 0.5
""".strip(),
        encoding="utf-8",
    )

    captured = {}

    def _fake_run_multi_personality_backtest(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(run_id="mp-test", total_duration=0.0, trading_days=0, personality_results={})

    monkeypatch.setattr("run._validate_environment", lambda mode=None, verbose=True: True)
    monkeypatch.setattr("run._validate_backtest_date_range", lambda *args, **kwargs: True)
    monkeypatch.setattr("run._print_multi_personality_results", lambda comparison, cashflow: None)
    monkeypatch.setattr(mp_engine, "run_multi_personality_backtest", _fake_run_multi_personality_backtest)

    args = _make_args(
        config=str(config_path),
        tickers=None,
        personalities="fof,balanced",
        analysts=DEFAULT_BACKTEST_ANALYSTS_ARG,
        market="cn",
        max_workers=3,
    )

    exit_code = run_multi_personality_mode(args)

    assert exit_code == 0
    assert captured["tickers"] == ["MSFT", "NVDA"]
    assert captured["personalities"] == ["fof", "balanced"]
    assert captured["initial_cash"] == 180000.0
    assert captured["market"] == "us"
    assert captured["analysts"] == ["fundamental"]
    assert captured["use_llm"] is True
    assert captured["max_workers"] == 3
    assert captured["config"]["api_source"]["us_source"] == "fmp"
    assert captured["config"]["llm"]["model"] == "deepseek-v3.2"
    assert captured["config"]["trading"]["market"] == "US"
