## Why

`add-wal-busytimeout-to-deepear-db` needs `deepear/src/utils/database_manager.py`
to add a module-level `from shared.db import configure_sqlite_connection,
ensure_parent_dir`. That module is reached through three different load
paths — a plain dotted import, deepfund's `importlib.util.spec_from_file_location`
hack in `deepfund/src/integrations/deepear_client.py`, and a worker-process
import inside `deepfund/src/agents/analysts/technical.py` — none of which
call `shared.utils.path_manager.setup_paths()` themselves. Before adding a
permanent dependency on `shared.db`, we need proof (not assumption) that all
three mechanisms actually resolve it in a fresh process.

## What Changes

- Spike only — no production behavior change. Adds a subprocess-based pytest
  spike (`tests/test_deepear_shared_import_spike.py`) that exercises each of
  the three load mechanisms in an isolated `sys.executable` child process
  with a minimal, hand-picked environment (no ambient `PYTHONPATH`, no
  `setup_paths()` call anywhere in the child).
- Records the findings in `design.md`: all three mechanisms resolve
  `shared.db` without any defensive/fallback import code, primarily because
  `quantarena` is installed editable (`pip install -e .`) in the target
  venv, so `shared`, `deepear`, and `deepfund` are importable via the
  editable-install finder independent of `sys.path` state.
- No fallback code is added to `database_manager.py` by this change — the
  spike found none was needed. The `from shared.db import ...` line itself
  is added by the follow-on change `add-wal-busytimeout-to-deepear-db`.

## Capabilities

### New Capabilities
- `deepear-shared-db-import`: documents and regression-tests that
  `deepear/src/utils/database_manager.py` can import `shared.db` under all
  of its real-world load mechanisms.

### Modified Capabilities
- None.

## Impact

- New test file only (`tests/test_deepear_shared_import_spike.py`). No
  production code changed by this proposal.
