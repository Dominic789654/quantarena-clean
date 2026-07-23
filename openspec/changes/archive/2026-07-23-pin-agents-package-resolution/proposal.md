## Why

Both `deepear/src` and `deepfund/src` define a top-level `agents` package, so `import agents` resolves to whichever path lands first on `sys.path`. Today the winner is decided by import order and per-test-file `sys.path.insert` workarounds (e.g. `tests/test_workflow_adapter_smart_priority.py`, `tests/test_base_analyst.py`), which is fragile and undocumented. The planned decomposition of `workflow_adapter.py`, `run.py`, and `report_agent.py` (docs/refactor_program_plan.md) creates many new leaf modules that lazily `from agents.registry import ...`; without a central resolution guarantee, each of them is exposed to whichever test file happens to be collected first.

## What Changes

- `shared/utils/path_manager.setup_paths()` guarantees deterministic package resolution: `deepfund/src` is placed ahead of `deepear/src` on `sys.path` even when both paths are already present (today it only skips existing entries, so pre-existing order wins).
- Add an autouse, session-scoped safety net in `tests/conftest.py` that pins `agents` (deepfund's) into `sys.modules` at session start, so collection order can never flip the winner mid-suite.
- Remove now-redundant per-test-file `sys.path.insert` workarounds where they exist solely for the `agents` collision (keep any that serve other purposes).
- Document the resolution rule in `path_manager.py` (deepfund's `agents` is canonical for bare imports; deepear code must import via `deepear.src.agents.*`).
- No breaking changes: deepear code already imports its own agents via the fully-qualified `deepear.src.agents.*` form.

## Capabilities

### New Capabilities
- `package-path-resolution`: Deterministic `sys.path` ordering and `agents` package resolution across the deepear/deepfund dual-package workspace, for both runtime entry points and the test suite.

### Modified Capabilities
- None.

## Impact

- `shared/utils/path_manager.py`: reorder-if-present logic.
- `tests/conftest.py`: session-scoped resolution pin.
- A handful of test files lose their local `sys.path` workarounds.
- Unblocks the decomposition tracks in docs/refactor_program_plan.md (workflow_adapter steps 7/9/11, runner mode handlers, report package) whose new leaf modules import `agents.*` lazily.
