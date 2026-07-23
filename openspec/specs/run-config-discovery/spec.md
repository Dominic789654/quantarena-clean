# run-config-discovery Specification

## Purpose
TBD - created by archiving change extract-run-config-discovery. Update Purpose after archive.
## Requirements
### Requirement: DeepFund config candidate ordering
`runner.config_discovery._get_deepfund_config_candidates` SHALL return an ordered list of candidate YAML config paths under `deepfund/src/config/` based on the requested market, preferring `exp_a_share.yaml`/`ashare.yaml` for CN markets and, for US markets, ordering `exp_us_stocks.yaml`, `dev.yaml`, `us.yaml` unless the resolved US data provider is `fmp`, in which case `us.yaml` SHALL be preferred over `dev.yaml`.

#### Scenario: CN market candidates
- **WHEN** `_get_deepfund_config_candidates("cn")` is called
- **THEN** it returns `[exp_a_share.yaml, ashare.yaml]` under `deepfund/src/config/`

#### Scenario: US market candidates prefer FMP template when FMP is the resolved provider
- **WHEN** `_get_deepfund_config_candidates("us")` is called and `preferred_us_data_provider` resolves to `fmp`
- **THEN** the returned order is `[exp_us_stocks.yaml, us.yaml, dev.yaml]`

#### Scenario: Unknown market falls back to dev.yaml
- **WHEN** `_get_deepfund_config_candidates(None)` or an unrecognized market string is called
- **THEN** it returns `[dev.yaml]`

### Requirement: YAML config loading
`runner.config_discovery._load_yaml_config_file` SHALL return an empty dict when given `None`, SHALL raise `ValueError` when the file is missing or not a YAML mapping, and SHALL raise `ValueError` wrapping any `yaml.YAMLError` on parse failure.

#### Scenario: None path returns empty config
- **WHEN** `_load_yaml_config_file(None)` is called
- **THEN** it returns `{}`

#### Scenario: Missing file raises ValueError
- **WHEN** `_load_yaml_config_file(Path("/does/not/exist.yaml"))` is called
- **THEN** a `ValueError` mentioning the missing path is raised

### Requirement: Backtest config file selection
`runner.config_discovery._select_backtest_config_file` SHALL return `args.config` as a `Path` when explicitly set, otherwise SHALL return the FOF template (`deepfund/src/config/fof.yaml`) when the single `personality` or any entry in the comma-separated `personalities` argument is `"fof"` (case-insensitive) and that file exists, otherwise SHALL return `None`.

#### Scenario: Explicit config wins
- **WHEN** `args.config` is set
- **THEN** that path is returned regardless of personality

#### Scenario: FOF personality selects the FOF template
- **WHEN** `args.config` is unset and `args.personality == "fof"` and `deepfund/src/config/fof.yaml` exists
- **THEN** that path is returned

### Requirement: run.py re-exports config discovery helpers
`run.py` SHALL expose `_get_deepfund_config_candidates`, `_load_yaml_config_file`, and `_select_backtest_config_file` as module attributes re-exported from `runner.config_discovery`, so existing `from run import ...` imports continue to resolve.

#### Scenario: Existing test imports keep working
- **WHEN** `tests/test_run_config_selection.py` runs `from run import VALID_PERSONALITIES, _get_deepfund_config_candidates`
- **THEN** the import succeeds and returns the function object defined in `runner.config_discovery`

