## 1. Path manager

- [x] 1.1 Change `setup_paths()` from skip-if-present to reorder-if-present: remove managed entries already on `sys.path`, re-insert in canonical order (`deepfund/src` before `deepear/src`); add `force=True` parameter to bypass the `_initialized` guard.
- [x] 1.2 Document the canonical order and the dual-`agents` rationale in the module docstring (bare `import agents` == deepfund's registry; deepear uses `deepear.src.agents.*`).
- [x] 1.3 Unit tests: pre-polluted path corrected, idempotency, unmanaged entries preserved.

## 2. Test-session pin

- [x] 2.1 Autouse session-scoped fixture in `tests/conftest.py`: `setup_paths(force=True)` then import `agents.registry`, assert `__file__` under `deepfund/src/agents/`.
- [x] 2.2 Remove per-test-file `sys.path.insert` workarounds that exist solely for the `agents` collision (audit the ~29 files; keep inserts serving other purposes, e.g. loading `run.py` helpers).

## 3. Verification

- [x] 3.1 Full suite green at the sanctioned baseline (910 passed / 10 skipped in `.venv_unified`).
- [ ] 3.2 `ruff check .` clean; CI green on PR.
- [x] 3.3 Spot-check the two runtime entry points (`python run.py --check-env`, `python -m quantarena.cli smoke --json`) still work in a fresh process.
