# package-path-resolution Specification

## Purpose
TBD - created by archiving change pin-agents-package-resolution. Update Purpose after archive.
## Requirements
### Requirement: Deterministic sys.path ordering for managed packages
`shared.utils.path_manager.setup_paths()` SHALL leave `sys.path` with the managed entries in canonical order — `deepfund/src` before `deepear/src` — regardless of whether any managed entry was already present before the call.

#### Scenario: Pre-polluted path is corrected
- **WHEN** `deepear/src` is already on `sys.path` ahead of `deepfund/src` and `setup_paths()` is called
- **THEN** after the call, `sys.path.index(deepfund_src) < sys.path.index(deepear_src)` holds

#### Scenario: Idempotent under repeat calls
- **WHEN** `setup_paths()` is called multiple times in one process
- **THEN** managed entries appear exactly once each and unmanaged entries keep their relative order

### Requirement: Bare `agents` package resolves to deepfund
In any process bootstrapped through `setup_paths()`, `import agents` SHALL resolve to `deepfund/src/agents` (the analyst registry package), and this SHALL be documented in `path_manager.py`.

#### Scenario: Registry import resolves canonically
- **WHEN** a module executes `from agents.registry import AgentRegistry` after `setup_paths()`
- **THEN** the imported module's `__file__` is under `deepfund/src/agents/`

### Requirement: Bare `utils` package resolves to deepear
In any process bootstrapped through `setup_paths()`, `import utils` SHALL resolve to `deepear/src/utils` (report_agent, search_tools, and deepear_client rely on bare `utils.*` imports); `shared/utils` SHALL only be reachable via the fully-qualified `shared.utils.*` form.

#### Scenario: Lazy visualizer import resolves canonically
- **WHEN** a module executes `from utils.visualizer import ...` after `setup_paths()`
- **THEN** the imported module's `__file__` is under `deepear/src/utils/`

### Requirement: Test session pins resolution once
The test suite SHALL pin the canonical `agents` resolution at session start via an autouse fixture so pytest collection order cannot change which package bare imports resolve to mid-session.

#### Scenario: Collection order cannot flip resolution
- **WHEN** a test file that manipulates `sys.path` is collected before a test file that imports `agents.registry`
- **THEN** `agents.registry` still resolves to `deepfund/src/agents` because the session pin already cached it in `sys.modules`

