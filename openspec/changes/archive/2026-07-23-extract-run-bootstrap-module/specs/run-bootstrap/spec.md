## ADDED Requirements

### Requirement: Tushare token-file repair
`runner.bootstrap._fix_tushare_token_file` SHALL remove a corrupted `~/tk.csv` Tushare token file when it exists, is writable, and either fails to parse as CSV or lacks a `token` column, and SHALL emit a `RuntimeWarning` instead of raising when the file cannot be removed due to permissions or OS errors.

#### Scenario: Corrupted token file is removed
- **WHEN** `~/tk.csv` exists, is writable, and does not contain a `token` column
- **THEN** the file is removed and no exception propagates

#### Scenario: Unwritable token file warns instead of raising
- **WHEN** `~/tk.csv` exists but `os.access(path, os.W_OK)` is `False`
- **THEN** a `RuntimeWarning` is emitted and the file is left in place

#### Scenario: Missing token file is a no-op
- **WHEN** `~/tk.csv` does not exist
- **THEN** the function returns immediately without error

### Requirement: Dotenv loading helper
`runner.bootstrap.load_dotenv_file` SHALL load environment variables from the given `.env` path using `dotenv.load_dotenv`, matching the behavior previously inlined in `run.py`'s `run_deepfund`.

#### Scenario: Env file loaded for deepfund mode
- **WHEN** `load_dotenv_file(PROJECT_ROOT / ".env")` is called
- **THEN** `dotenv.load_dotenv` is invoked with that path and any variables it defines become available via `os.environ`

### Requirement: run.py re-exports bootstrap helpers
`run.py` SHALL expose `_fix_tushare_token_file` and `load_dotenv_file` as module attributes re-exported from `runner.bootstrap`, so existing `from run import _fix_tushare_token_file` imports and any future `monkeypatch.setattr("run._fix_tushare_token_file", ...)` / `monkeypatch.setattr("run.load_dotenv_file", ...)` continue to resolve.

#### Scenario: Re-export satisfies existing import
- **WHEN** `tests/test_type_annotations.py` runs `from run import _fix_tushare_token_file`
- **THEN** the import succeeds and returns the same function object defined in `runner.bootstrap`
