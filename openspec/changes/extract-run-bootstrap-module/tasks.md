## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "monkeypatch.setattr" tests/ | grep "'run\.\|\"run\."` and
  `git grep -n "from run import\|import run\b" tests/` for
  `_fix_tushare_token_file`, `setup_paths`, `load_dotenv`,
  `get_project_root`, `get_deepfund_src` — no monkeypatch hits; only a
  plain `from run import _fix_tushare_token_file` in
  `tests/test_type_annotations.py`.

## 2. Implementation

- [x] 2.1 Add `runner/__init__.py` (real package).
- [x] 2.2 Add `runner/bootstrap.py` with `_fix_tushare_token_file`
  (verbatim) and `load_dotenv_file` (lifted out of `run_deepfund`).
- [x] 2.3 `run.py`: replace the `_fix_tushare_token_file` definition with
  `from runner.bootstrap import _fix_tushare_token_file, load_dotenv_file
  # noqa: F401`; keep the immediate `_fix_tushare_token_file()` call at
  the same source position.
- [x] 2.4 `run.py`'s `run_deepfund`: replace the inline
  `from dotenv import load_dotenv; load_dotenv(PROJECT_ROOT / ".env")`
  with `load_dotenv_file(PROJECT_ROOT / ".env")`.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` — 928 passed, 10
  skipped, 0 failed (baseline unchanged).
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
- [x] 3.3 `python run.py --check-env` exits 0.
