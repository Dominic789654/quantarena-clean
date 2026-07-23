## Context

Post `extract-run-cli-support-helpers`, `run.py`'s remaining functions
are the three targeted here plus `_validate_backtest_date_range`,
`_execute_backtest_mode`, `run_backtest_mode`,
`run_multi_personality_mode` (all out of scope, step 7), and `main`
(out of scope, step 8). `run_deepear` and `run_deepfund` each use
`run.py`'s module-level `PROJECT_ROOT`/`DEEPFUND_SRC` globals;
`run_full_pipeline` calls `run_deepear` and `run_deepfund` and the
module-level `get_stats` import.

## Goals / Non-Goals

**Goals:** move the three handlers verbatim; close the
`run_full_pipeline` skip-flag/continue-on-error coverage gap; keep
every `run.<name>` re-export and `from run import <name>` import
working; decide (with justification) whether the three handlers live in
one file or three.

**Non-Goals:** touching `_validate_backtest_date_range`,
`_execute_backtest_mode`, `run_backtest_mode`,
`run_multi_personality_mode`, or `main()`.

## Decisions

1. **Three files, not one `runner/modes.py`.** The ticket offered
   either shape. Splitting into `deepear.py`/`deepfund.py`/
   `pipeline.py` was chosen because each handler pulls in a distinct,
   non-overlapping import surface (DeepEar's `main_flow`/
   `utils.logging_setup` lazy imports; DeepFund's
   `importlib.util.spec_from_file_location` exec-module dance and
   `.env` loading; the pipeline's orchestration of the other two) --
   keeping them in separate modules means importing `runner.modes.
   deepear` alone (e.g. from a future DeepEar-only consumer) never
   pulls in DeepFund's importlib machinery, and each file's diff/grep
   surface stays scoped to one subsystem. This mirrors the plan's own
   file list (`runner/modes/{deepear,deepfund,pipeline}.py`) rather
   than its parenthetical alternative.
2. **`PROJECT_ROOT`/`DEEPFUND_SRC` substitution, not relocation.**
   Unlike `DEFAULT_BACKTEST_ANALYSTS_ARG`/`VALID_PERSONALITIES` in
   `extract-run-runtime-options` (which had no "call the source of
   truth" option and so moved as literal constants), `PROJECT_ROOT` and
   `DEEPFUND_SRC` are just cached results of `get_project_root()` /
   `get_deepfund_src()` -- calling those functions again inside the
   moved handlers reproduces the identical value with no relocation
   needed, exactly the pattern `runner/config_discovery.py` and
   `runner/env_validation.py` already established. `run.py` no longer
   needs either global once both handlers leave, so both were deleted
   from `run.py` rather than kept as now-pointless module state; no
   test imports `run.PROJECT_ROOT`/`run.DEEPFUND_SRC` (grep confirmed
   -- every test file that references a `PROJECT_ROOT` name defines its
   own local one via `Path(__file__)`).
3. **`setup_paths()` call site is unchanged.** Per the
   `extract-run-bootstrap-module` decision record, reordering
   `setup_paths()` against `shared.config.*`/other early imports is out
   of scope for any Phase 2 step -- only the *consumers* of
   `get_project_root()`/`get_deepfund_src()` moved, not the
   path-setup call itself.
4. **No `_shim` needed.** All three functions' internal calls
   (`run_deepear`/`run_deepfund` calling `_validate_environment`;
   `run_full_pipeline` calling `run_deepear`/`run_deepfund`) resolve
   against names with zero `run.*`-string monkeypatch coverage (see
   proposal.md audit). This is the first Phase 2 step since
   `add-run-module-shim-and-env-validation` that needs no shim routing
   at all -- the high-monkeypatch-density backtest/multi-personality
   handlers are deliberately deferred to step 7.
5. **New tests target the real coverage gap, not a re-test of
   run_deepear/run_deepfund's own bodies** (those already have
   `ImportError`/`Exception` branch coverage via
   `test_type_annotations.py`'s introspection and, indirectly, via
   `--check-env`/subprocess smokes). `run_full_pipeline` itself had
   *zero* coverage before this change -- neither the skip flags nor
   `continue_on_error`'s short-circuit-vs-continue behavior were
   exercised anywhere. The six new tests stub `run_deepear`/
   `run_deepfund` directly on `runner.modes.pipeline` (not on `run`,
   since nothing patches them there) and assert on call order and the
   returned exit code for: skip-deepear-only, skip-deepfund-only,
   skip-both, skip-neither, deepear-fails-without-continue-on-error
   (short-circuits), deepear-fails-with-continue-on-error (both run,
   `max()` exit code).

## Risks / Trade-offs

- None material: zero monkeypatch coverage on any of the three moved
  functions; the `PROJECT_ROOT`/`DEEPFUND_SRC` substitution is
  byte-identical in value to the deleted globals.
