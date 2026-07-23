## Context

`shared/utils/path_manager.py` `setup_paths()` inserts `PROJECT_ROOT`, `deepear/src`, `deepfund/src`, `shared`, `backtest` into `sys.path` with `insert(0, ...)`, skipping entries that are already present. Because it skips-if-present, a process (or pytest session) that already has `deepear/src` on the path before `deepfund/src` keeps that order forever, and `import agents` silently resolves to `deepear/src/agents` (fin/trend/report agents) instead of `deepfund/src/agents` (analyst registry). pytest's `pythonpath = [".", "deepear/src", "deepfund/src", "shared"]` (pyproject) plus per-file `sys.path.insert(0, deepfund/src)` hacks currently paper over this in ~29 test files.

The refactor program (docs/refactor_program_plan.md) will introduce new leaf modules under `backtest/workflow/`, `runner/`, and `deepear/src/agents/report/` that lazily import `agents.registry` / `graph.schema`; each would inherit this fragility.

## Goals / Non-Goals

**Goals:**
- One documented, deterministic rule: bare `import agents` (and sibling bare packages `graph`, `apis`, `llm`, `util`) resolves to `deepfund/src`.
- The rule holds regardless of prior `sys.path` state and pytest collection order.
- Existing tests keep passing without their local workarounds.

**Non-Goals:**
- Renaming either `agents` package (that is the roadmap's long-term `src/quantarena/` restructuring, out of scope here).
- Changing how deepear code imports its own agents (`deepear.src.agents.*` stays).

## Decisions

1. **Reorder-if-present in `setup_paths()`**: instead of skip-if-present, remove any of the managed paths already on `sys.path` and re-insert the full managed prefix in canonical order (`backtest`, `shared`, `deepfund/src`, `deepear/src`, `PROJECT_ROOT` — final `sys.path` order therefore puts `deepfund/src` before `deepear/src`). Idempotent; leaves unmanaged entries untouched and preserves their relative order.
2. **Session pin in conftest**: an autouse session fixture imports `agents.registry` once after `setup_paths()`, asserting it came from `deepfund/src`, and leaves the module in `sys.modules`. Collection order then cannot flip the resolution mid-suite (module cache wins).
3. **Keep `_initialized` guard but allow explicit re-run**: add `setup_paths(force=True)` for the conftest pin so a half-initialized interpreter can still be corrected.

## Risks / Trade-offs

- Any code that (incorrectly) relied on bare `import agents` resolving to deepear's package would break loudly. Mitigation: repo-wide grep shows deepear-internal code always uses `deepear.src.agents.*`; the one-off importlib loaders in `deepfund/src/integrations/deepear_client.py` load by file path and are unaffected.
- Reordering `sys.path` in a library function is surprising to newcomers. Mitigation: the module docstring documents the canonical order and the reason (dual `agents` packages).
