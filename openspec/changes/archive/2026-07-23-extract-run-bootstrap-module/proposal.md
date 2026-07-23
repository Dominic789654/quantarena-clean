## Why

`run.py` (1218 lines) is the second target of the decomposition program
(docs/refactor_program_plan.md Phase 2). Its module top mixes bootstrap
concerns inline: the Tushare `tk.csv` corruption workaround that must run
before other imports, and (inside `run_deepfund`) ad hoc `.env` loading.
Neither is backtest- or CLI-specific; splitting them into a dedicated
`runner/` package is the cheapest, lowest-risk first step and establishes
the package tests will keep monkeypatching through `run.<name>`
re-exports.

## What Changes

- Add `runner/` package (`runner/__init__.py`) and `runner/bootstrap.py`
  holding `_fix_tushare_token_file` (moved verbatim from `run.py`) and
  `load_dotenv_file` (the two-line `.env` load lifted out of
  `run_deepfund`'s body, unchanged logic, now callable as one function).
- `run.py` re-exports `_fix_tushare_token_file` and `load_dotenv_file`
  from `runner.bootstrap` and calls them at the same point in module
  execution as before (no timing change).
- The `setup_paths()` / `get_project_root()` / `get_deepfund_src()`
  sequence at `run.py`'s module top stays in `run.py` unchanged: those
  names are owned by `shared.utils.path_manager`, not defined in
  `run.py`, so there is no run.py-owned code to move for that step, and
  relocating the *call site* risks reordering it relative to the
  `shared.config.*` imports that currently precede `setup_paths()` — a
  risk not justified for a package-boundary-only change. Grouping that
  sequence into `runner/` is deferred to a later, explicitly-scoped step
  if ever needed.
- No behavior change: same functions, same call order, same return
  values.

## Capabilities

### New Capabilities
- `run-bootstrap`: the tushare-token-file fix and `.env` loading helpers
  used by `run.py` before mode-specific code runs.

### Modified Capabilities
- None.

## Impact

- `run.py`, new `runner/__init__.py`, `runner/bootstrap.py`.
- Monkeypatch audit (ground rule 3): `git grep` found no
  `monkeypatch.setattr("run._fix_tushare_token_file", ...)` or
  `run.load_dotenv` patches anywhere in `tests/`.
  `tests/test_type_annotations.py` does `from run import
  _fix_tushare_token_file` (import, not monkeypatch) — satisfied by the
  re-export. `tests/test_file_permission_check.py` never imports `run` at
  all (it re-implements the permission-check logic inline for testing).
  No internal caller→callee pair moved together in this change requires
  the `_shim` indirection.
