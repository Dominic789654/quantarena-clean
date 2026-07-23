## 1. Spike

- [x] 1.1 Empirically probe each of the three load mechanisms via ad-hoc
  subprocess runs (normal dotted import, deepfund's importlib hack, fork
  worker) to establish ground truth before writing the permanent test.
- [x] 1.2 Author `tests/test_deepear_shared_import_spike.py`: one
  subprocess-isolated test per mechanism (plus a negative control for
  mechanism 2), asserting `shared.db` resolves without `setup_paths()`.
- [x] 1.3 Record findings in `design.md`: all three mechanisms resolve via
  the `quantarena` editable install's package discovery; no fallback
  import code needed in `database_manager.py`.

## 2. Verification

- [x] 2.1 `tests/test_deepear_shared_import_spike.py` green in isolation
  (5 passed).
- [x] 2.2 Full suite green at baseline; ruff clean.
