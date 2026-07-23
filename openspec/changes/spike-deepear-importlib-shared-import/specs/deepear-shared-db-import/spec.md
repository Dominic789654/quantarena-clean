## ADDED Requirements

### Requirement: shared.db resolves under every deepear database_manager load mechanism
`deepear/src/utils/database_manager.py`'s `from shared.db import configure_sqlite_connection` statement SHALL resolve successfully in a fresh process, without any prior call to `shared.utils.path_manager.setup_paths()`, under each of the three ways the module is loaded in production: a normal dotted import, deepfund's `importlib.util.spec_from_file_location` loader, and a worker-process import inside a `ProcessPoolExecutor` child.

#### Scenario: Normal dotted import resolves with zero path configuration
- **WHEN** a fresh subprocess with no `PYTHONPATH` and a cwd outside the
  project root runs `from deepear.src.utils.database_manager import
  DatabaseManager`
- **THEN** the import succeeds and `shared.db` is resolvable in that same
  process

#### Scenario: deepfund's importlib hack resolves shared.db inside the loaded module
- **WHEN** `deepfund/src/integrations/deepear_client.py`'s
  `importlib.util.spec_from_file_location` mechanism loads
  `database_manager.py` under the synthetic module name
  `"utils.database_manager"`, reached via the bare `integrations.deepear_client`
  import with only `deepfund/src` on `PYTHONPATH` (no project root added
  explicitly)
- **THEN** the loaded module's own `from shared.db import
  configure_sqlite_connection` succeeds

#### Scenario: Worker-process (forked) import resolves shared.db
- **WHEN** a `multiprocessing.get_context("fork")` child process — mirroring
  `ProcessPoolExecutor`'s default Linux start method used by
  `backtest/multi_personality_engine.py` — performs the same import as
  `deepfund/src/agents/analysts/technical.py:81`
- **THEN** the import succeeds inside the child process, both with zero
  path configuration and with only the project root on `PYTHONPATH`

#### Scenario: No defensive fallback import is required
- **WHEN** any of the three mechanisms above is exercised in a fresh
  process without `setup_paths()` having been called
- **THEN** `shared.db` resolves via the `quantarena` editable install's
  package-discovery configuration (`pyproject.toml`
  `[tool.setuptools.packages.find]`) alone, and no `try/except ImportError`
  fallback around the `shared.db` import is needed in
  `database_manager.py`
