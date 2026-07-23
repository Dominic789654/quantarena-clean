## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "monkeypatch" tests/ | grep -E
  "run_deepear|run_deepfund|run_full_pipeline"` -- no hits.
- [x] 1.2 `git grep -n "PROJECT_ROOT\|DEEPFUND_SRC" run.py tests/` to
  confirm no test imports `run.PROJECT_ROOT`/`run.DEEPFUND_SRC` (every
  test-local `PROJECT_ROOT` is independently derived from
  `Path(__file__)`).

## 2. Implementation

- [x] 2.1 Add `runner/modes/__init__.py` (package docstring only, no
  re-exports -- mirrors `runner/__init__.py`).
- [x] 2.2 Add `runner/modes/deepear.py` with `run_deepear` moved
  verbatim, substituting `get_project_root()` calls for the two
  `PROJECT_ROOT` references.
- [x] 2.3 Add `runner/modes/deepfund.py` with `run_deepfund` moved
  verbatim, substituting `get_project_root()`/`get_deepfund_src()`
  calls for the `PROJECT_ROOT`/`DEEPFUND_SRC` references.
- [x] 2.4 Add `runner/modes/pipeline.py` with `run_full_pipeline` moved
  verbatim, importing `run_deepear`/`run_deepfund` from the sibling
  modules and `get_stats` from `deepear.src.utils.stats`.
- [x] 2.5 `run.py`: replace the three definitions with
  `from runner.modes.deepear import run_deepear`,
  `from runner.modes.deepfund import run_deepfund`,
  `from runner.modes.pipeline import run_full_pipeline`  (each
  `# noqa: F401`).
- [x] 2.6 `run.py`: delete the `PROJECT_ROOT`/`DEEPFUND_SRC` global
  assignments and the now-unused `get_project_root`, `get_deepfund_src`,
  `now_utc`, `get_stats` imports; keep the `setup_paths()` call and its
  import at the same source position.
- [x] 2.7 Add `tests/test_run_full_pipeline_skip_flags.py` with the six
  skip-flag/continue-on-error scenarios described in design.md,
  stubbing `run_deepear`/`run_deepfund` on `runner.modes.pipeline`.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` -- 935 passed
  (929 baseline + 6 new), 10 skipped, 0 failed.
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
- [x] 3.3 `python run.py --check-env` exits 0.
- [x] 3.4 `python run.py --mode full --skip-deepear --skip-deepfund
  --no-banner` exits 0 (real end-to-end invocation of the moved
  `run_full_pipeline`, not just an import-level check).
