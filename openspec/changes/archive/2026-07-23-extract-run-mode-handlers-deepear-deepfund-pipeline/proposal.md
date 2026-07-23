## Why

Continuing the run.py decomposition (docs/refactor_program_plan.md Phase
2, step 6 of 8): `run_deepear`, `run_deepfund`, and `run_full_pipeline`
are the three simplest mode handlers -- none of them are involved in
the high monkeypatch density that the backtest/multi-personality mode
handlers carry (step 7). They also have a coverage gap the plan calls
out explicitly: `run_full_pipeline`'s `--skip-deepear`/`--skip-deepfund`
branches and its `continue_on_error` propagation logic have zero test
coverage today.

## What Changes

- Add `runner/modes/` (`__init__.py` + `deepear.py`, `deepfund.py`,
  `pipeline.py`) holding, moved verbatim from `run.py`: `run_deepear`,
  `run_deepfund`, `run_full_pipeline`.
- `run.py` re-exports all three from their new modules.
- `run.py`'s module-level `PROJECT_ROOT`/`DEEPFUND_SRC` globals (and the
  `get_project_root`/`get_deepfund_src`/`now_utc`/`get_stats` imports
  that fed them or were only used inside the moved functions) are
  removed from `run.py`; the two mode-handler modules that need a
  project root or deepfund src path call `get_project_root()` /
  `get_deepfund_src()` directly, mirroring the substitution already
  used in `runner/config_discovery.py` and `runner/env_validation.py`.
  `run.py`'s `setup_paths()` call keeps its original source position
  (per the `extract-run-bootstrap-module` precedent: reordering it
  against `shared.config.*` imports is out of scope and risky).
- Add `tests/test_run_full_pipeline_skip_flags.py`: 6 new tests
  covering `--skip-deepear` alone, `--skip-deepfund` alone, both
  skipped, neither skipped, and `continue_on_error` True/False when the
  DeepEar phase fails -- the zero-coverage gap named above.

## Capabilities

### New Capabilities
- `run-deepear-deepfund-pipeline-modes`: the DeepEar-only,
  DeepFund-only, and combined-pipeline CLI mode handlers, including the
  pipeline's skip-flag and continue-on-error semantics.

### Modified Capabilities
- None.

## Impact

- `run.py`, new `runner/modes/__init__.py`, `runner/modes/deepear.py`,
  `runner/modes/deepfund.py`, `runner/modes/pipeline.py`, new
  `tests/test_run_full_pipeline_skip_flags.py`.
- Monkeypatch audit (ground rule 3):
  `git grep -n "monkeypatch" tests/ | grep -E
  "run_deepear|run_deepfund|run_full_pipeline"` returns nothing --
  zero monkeypatch coverage on any of the three moved functions.
  `tests/test_type_annotations.py` does plain
  `from run import run_deepear` / `from run import run_deepfund`
  (satisfied by the re-export; type-hint introspection is unaffected by
  which module defines the function). No `_shim` indirection is needed
  anywhere in this change: `run_deepear`/`run_deepfund` call
  `_validate_environment` (already living in `runner/env_validation.py`
  since a prior change, not independently monkeypatched for these two
  handlers), and `run_full_pipeline` calls `run_deepear`/`run_deepfund`
  via plain intra-package imports from its sibling modules -- neither
  callee is ever monkeypatched via a `run.*` string path, so there is
  no caller-left-run.py-while-callee-still-patched-on-run trap to
  close.
