## Context

`run.py:18-71` defines and immediately calls `_fix_tushare_token_file()`
before importing `shared.utils.path_manager`. `run.py:573-576` (inside
`run_deepfund`) imports `dotenv.load_dotenv` locally and loads
`PROJECT_ROOT / ".env"`.

## Goals / Non-Goals

**Goals:** relocate these two bootstrap concerns into `runner/bootstrap.py`
without changing when or how they run; keep every `run.<name>`
monkeypatch path and `from run import <name>` import working via
re-export.

**Non-Goals:** changing `setup_paths()` itself (owned by
`shared.utils.path_manager`, out of scope) or moving its call site;
adding new dotenv-loading call sites; refactoring `run_deepfund`'s
control flow beyond swapping the inline `load_dotenv` call for
`load_dotenv_file`.

## Decisions

1. `load_dotenv_file(env_path)` is a new one-line wrapper around the
   `dotenv.load_dotenv` call previously inlined in `run_deepfund`; the
   local `from dotenv import load_dotenv` import moves with it, kept
   local to the function (matching the original's lazy-import style). No
   test patches `run.load_dotenv`, so this is safe.
2. `_fix_tushare_token_file` moves verbatim (docstring, local `import
   warnings` / `import pandas as pd`, all branches unchanged).
3. `run.py` imports both names with `from runner.bootstrap import
   _fix_tushare_token_file, load_dotenv_file  # noqa: F401` at the exact
   source position the function definitions used to occupy, then calls
   `_fix_tushare_token_file()` immediately after — preserving "fix runs
   before any other run.py import" exactly. `runner/bootstrap.py` itself
   imports only `os` and `warnings` at module level (no `pandas`, no
   `shared.*`), so importing it introduces no new eager imports ahead of
   the fix.
4. No internal caller in `runner/bootstrap.py` calls back into `run.py`,
   so this change needs no `_shim` indirection (that need starts at
   change 4, `add-run-module-shim-and-env-validation`).

## Risks / Trade-offs

- None material: both moved functions are leaf helpers with no
  monkeypatch coverage today; the module-level import surface of
  `runner/bootstrap.py` is deliberately kept minimal to avoid perturbing
  `run.py`'s import order.
