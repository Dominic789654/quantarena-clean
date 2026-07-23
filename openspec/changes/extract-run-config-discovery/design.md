## Context

`run.py:206-268` defines `_get_deepfund_config_candidates`,
`_load_yaml_config_file`, `_select_backtest_config_file`. The first and
third read the module-level `PROJECT_ROOT` global (set at `run.py`'s
module top from `get_project_root()`); the second is a pure YAML loader
with no module-level dependency. Callers
(`run_deepfund`, `_resolve_backtest_runtime_options`,
`_resolve_multi_personality_runtime_options`) remain in `run.py` for this
step — they move in later Phase 2 steps (runtime-options in step 3, mode
handlers later).

## Goals / Non-Goals

**Goals:** relocate the three discovery helpers verbatim; keep every
`run.<name>` re-export and `from run import <name>` import working;
resolve the `PROJECT_ROOT` global dependency without changing its
resolved value.

**Non-Goals:** touching the runtime-option resolvers or `run_deepfund`
(deferred to steps 3 and later); changing config-selection precedence or
YAML-loading error handling.

## Decisions

1. `_load_yaml_config_file` moves byte-for-byte — no module-global
   dependency.
2. `_get_deepfund_config_candidates` and `_select_backtest_config_file`
   replace the bare `PROJECT_ROOT` reference with
   `shared.utils.path_manager.get_project_root()` (imported at module
   level in `runner/config_discovery.py`). `run.py` computes
   `PROJECT_ROOT = get_project_root()` once at import time from the same
   function, so the returned `Path` is identical; this avoids inventing a
   `_shim`-style indirection for a plain data value when the direct
   source-of-truth call is simpler and equally verbatim in effect.
3. No caller moves in this change, so no monkeypatch-breaking
   caller/callee split occurs; the `_shim` module is not needed until
   change 4.

## Risks / Trade-offs

- None material: zero monkeypatch coverage on these three names; the
  `PROJECT_ROOT` → `get_project_root()` substitution is a like-for-like
  read of the same underlying value.
