## Why

Continuing the run.py decomposition (docs/refactor_program_plan.md Phase
2, step 2 of 8): `_get_deepfund_config_candidates`,
`_load_yaml_config_file`, and `_select_backtest_config_file` are pure
config-file-discovery helpers with no dependency on CLI argument parsing
or mode execution. They are the next-cheapest slice to extract after
`extract-run-bootstrap-module`, and none of them are monkeypatched by
tests, so this step carries essentially zero regression risk.

## What Changes

- Add `runner/config_discovery.py` holding `_get_deepfund_config_candidates`,
  `_load_yaml_config_file`, and `_select_backtest_config_file`, moved
  verbatim from `run.py`.
- The two functions that read `PROJECT_ROOT` (`_get_deepfund_config_candidates`,
  `_select_backtest_config_file`) call `shared.utils.path_manager.get_project_root()`
  directly instead of referencing run.py's module-level `PROJECT_ROOT`
  global — `PROJECT_ROOT = get_project_root()` in run.py, so this is the
  same value, just fetched at the source instead of through a global that
  would no longer be in scope after the move. This is the only deviation
  from a byte-for-byte move, and it is behavior-preserving
  (`get_project_root()` returns the same cached `Path` every call).
- `run.py` re-exports all three names from `runner.config_discovery`.

## Capabilities

### New Capabilities
- `run-config-discovery`: DeepFund YAML config candidate selection and
  loading used by both plain `deepfund` mode and the backtest/
  multi-personality runtime resolvers.

### Modified Capabilities
- None.

## Impact

- `run.py`, new `runner/config_discovery.py`.
- Monkeypatch audit (ground rule 3): `git grep -n "monkeypatch" tests/ |
  grep -E "_get_deepfund_config_candidates|_load_yaml_config_file|_select_backtest_config_file"`
  returns nothing — no test patches any of the three functions.
  `tests/test_run_config_selection.py` does `from run import
  VALID_PERSONALITIES, _get_deepfund_config_candidates` (plain import);
  `tests/test_backtest_fof_config_runtime.py` does `from run import (...,
  _select_backtest_config_file, ...)` (plain import). Both satisfied by
  the re-export.
- Callers of these three functions (`run_deepfund`,
  `_resolve_backtest_runtime_options`, `_resolve_multi_personality_runtime_options`)
  stay in `run.py` in this change, so the bare-name call sites resolve
  against `run.py`'s re-exported globals with no shim needed — the
  caller-and-callee-move trap (ground rule 3 / ticket item 3c) only bites
  when a caller moves to `runner/` *without* its callee staying reachable
  by name, which does not happen here.
