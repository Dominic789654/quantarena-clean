# run-env-validation Specification

## Purpose
TBD - created by archiving change add-run-module-shim-and-env-validation. Update Purpose after archive.
## Requirements
### Requirement: Full environment validation
`runner.env_validation._validate_environment` SHALL delegate to `shared.config.validator.validate_env(mode=mode, raise_on_error=True, verbose=verbose)`, SHALL return `True` when the validator module is unavailable (`ImportError`), and SHALL print a formatted quick-fix message to stderr and return `False` when validation raises `ValueError`.

#### Scenario: Missing validator module is treated as pass
- **WHEN** `shared.config.validator` cannot be imported
- **THEN** `_validate_environment` returns `True`

#### Scenario: Validation failure prints quick-fix guidance
- **WHEN** `validate_env` raises `ValueError` and `verbose=True`
- **THEN** a formatted error block including "cp .env.example .env" is printed to stderr and `False` is returned

### Requirement: Non-LLM backtest environment validation
`runner.env_validation._validate_non_llm_backtest_environment` SHALL require `TUSHARE_API_KEY` for CN-market non-LLM backtests, SHALL require the resolved US data provider's corresponding API key (`ALPHA_VANTAGE_API_KEY` or `FMP_API_KEY`) for US-market non-LLM backtests, and SHALL reject unsupported markets.

#### Scenario: CN backtest requires Tushare key
- **WHEN** `runtime["market"] == "cn"` and `TUSHARE_API_KEY` is unset
- **THEN** validation fails and a message naming `TUSHARE_API_KEY` is printed (when verbose)

#### Scenario: US backtest with unsupported provider fails closed
- **WHEN** `runtime["market"] == "us"` and the resolved provider is neither `alpha_vantage` nor `fmp`
- **THEN** validation fails with a message describing the supported providers

### Requirement: Backtest environment validation routes by use_llm
`runner.env_validation._validate_backtest_environment_for_runtime` SHALL call the full environment validator (mode="backtest") when `runtime["use_llm"]` is truthy, and SHALL otherwise call the non-LLM backtest validator, and SHALL observe any monkeypatch applied to `run._validate_environment` (or, when run.py is executing as `__main__`, `__main__._validate_environment`) for the LLM branch.

#### Scenario: LLM runtime uses the full validator, honoring monkeypatches on the public run module
- **WHEN** `runtime["use_llm"]` is truthy and a test has done `monkeypatch.setattr("run._validate_environment", fake)`
- **THEN** `_validate_backtest_environment_for_runtime` invokes `fake`, not its own local `_validate_environment`

#### Scenario: Non-LLM runtime uses the data-dependency validator
- **WHEN** `runtime["use_llm"]` is falsy
- **THEN** `_validate_non_llm_backtest_environment` is invoked with the same `runtime` and `verbose`

### Requirement: .env file bootstrap check
`runner.env_validation.check_env_file` SHALL return `True` when `.env` exists at the project root, SHALL copy `.env.example` to `.env` and return `False` when only the example exists, and SHALL return `False` with an error message when neither file exists.

#### Scenario: Missing .env is created from example
- **WHEN** `.env` does not exist but `.env.example` does
- **THEN** `.env` is created as a copy of `.env.example` and `check_env_file` returns `False`

### Requirement: run.py re-exports environment validation helpers
`run.py` SHALL expose `_validate_environment`, `_print_backtest_env_error`, `_configured_us_data_provider`, `_validate_non_llm_backtest_environment`, `_validate_backtest_environment_for_runtime`, and `check_env_file` as module attributes re-exported from `runner.env_validation`, so existing `run.<name>` monkeypatch string paths and `from run import <name>` imports continue to resolve.

#### Scenario: Existing monkeypatch paths keep working
- **WHEN** a test does `monkeypatch.setattr("run._validate_backtest_environment_for_runtime", fake)`
- **THEN** callers in `run.py` (e.g. `_execute_backtest_mode`, `run_multi_personality_mode`) observe `fake` because they call it by the re-exported bare name in `run.py`'s own namespace

