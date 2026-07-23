## ADDED Requirements

### Requirement: Public run-module resolution for cross-module internal calls
`runner._shim.run_module` SHALL return `sys.modules.get("run")` when that module exists and exposes a `_validate_environment` attribute, and SHALL otherwise return `sys.modules.get("__main__")`, so that code in `runner/` calling back into a name the public entry point re-exports observes any monkeypatch applied to that public entry point, whether it is imported as `run` or executing as `__main__`.

#### Scenario: Imported-as-run resolution
- **WHEN** `run.py` has been imported normally (so `sys.modules["run"]` exists and has `_validate_environment`)
- **THEN** `run_module()` returns that `run` module object

#### Scenario: Executed-as-script resolution
- **WHEN** `run.py` is executed directly (`python run.py ...`), so Python registers it as `sys.modules["__main__"]` and `"run"` is never added to `sys.modules`
- **THEN** `run_module()` returns `sys.modules["__main__"]`

#### Scenario: No usable module resolves to None
- **WHEN** neither `sys.modules["run"]` (with the expected attribute) nor `sys.modules["__main__"]` is available
- **THEN** `run_module()` returns `None`, and callers SHALL fall back to their local function definition rather than raising

### Requirement: Subprocess coverage of the __main__ fallback branch
The test suite SHALL include a test that executes `run.py` as a real subprocess (not an in-process import), so the `sys.modules.get("__main__")` branch of `runner._shim.run_module` has at least one exercised code path distinct from every monkeypatch-based test (which only exercises the `sys.modules.get("run")` branch).

#### Scenario: python run.py --check-env exits zero
- **WHEN** `subprocess.run([sys.executable, "run.py", "--check-env"], cwd=<project root>)` is invoked
- **THEN** the process exits with code 0
