# run-deepear-deepfund-pipeline-modes Specification

## Purpose
TBD - created by archiving change extract-run-mode-handlers-deepear-deepfund-pipeline. Update Purpose after archive.
## Requirements
### Requirement: DeepEar mode handler validates environment before running
`runner.modes.deepear.run_deepear` SHALL return `1` without running the DeepEar workflow when `_validate_environment(mode="deepear")` returns falsy, and SHALL otherwise construct a `SignalFluxWorkflow` and invoke `.run(...)` with the parsed sources/depth/query/checkpoint arguments, returning `0` on success and `1` on `ImportError` or any other exception.

#### Scenario: Failed environment validation short-circuits
- **WHEN** `_validate_environment(mode="deepear")` returns `False`
- **THEN** `run_deepear` returns `1` without importing `main_flow.SignalFluxWorkflow`

### Requirement: DeepFund mode handler validates environment and resolves a config file
`runner.modes.deepfund.run_deepfund` SHALL return `1` without executing DeepFund's `main()` when `_validate_environment(mode="deepfund")` returns falsy, SHALL fall back to `_get_deepfund_config_candidates(args.market)` when `args.config` is unset, and SHALL return `1` when the resolved trading date fails `YYYY-MM-DD` parsing.

#### Scenario: Invalid trading date is rejected before DeepFund runs
- **WHEN** `args.date` is set to a string that does not match `%Y-%m-%d`
- **THEN** `run_deepfund` prints an error naming the invalid date and returns `1` without calling DeepFund's `main()`

### Requirement: Full pipeline mode respects skip flags and continue-on-error
`runner.modes.pipeline.run_full_pipeline` SHALL skip the DeepEar phase when `args.skip_deepear` is true and skip the DeepFund phase when `args.skip_deepfund` is true, SHALL return immediately with a non-zero phase's exit code when that phase fails and `args.continue_on_error` is false, and SHALL otherwise run both non-skipped phases and return `max(deepear_exit, deepfund_exit)`.

#### Scenario: Both phases skipped runs neither
- **WHEN** `args.skip_deepear` and `args.skip_deepfund` are both true
- **THEN** neither `run_deepear` nor `run_deepfund` is called, and `run_full_pipeline` returns `0`

#### Scenario: DeepEar failure short-circuits without continue_on_error
- **WHEN** `run_deepear` returns a non-zero exit code and `args.continue_on_error` is false
- **THEN** `run_full_pipeline` returns that exit code immediately without calling `run_deepfund`

#### Scenario: DeepEar failure continues to DeepFund when continue_on_error is set
- **WHEN** `run_deepear` returns a non-zero exit code and `args.continue_on_error` is true
- **THEN** `run_deepfund` is still called, and `run_full_pipeline` returns `max(deepear_exit, deepfund_exit)`

### Requirement: run.py re-exports the DeepEar/DeepFund/pipeline mode handlers
`run.py` SHALL expose `run_deepear`, `run_deepfund`, and `run_full_pipeline` as module attributes re-exported from `runner.modes.deepear`, `runner.modes.deepfund`, and `runner.modes.pipeline` respectively, so existing `from run import <name>` imports (including type-hint introspection in `tests/test_type_annotations.py`) continue to resolve.

#### Scenario: Type-hint introspection keeps working after the move
- **WHEN** `tests/test_type_annotations.py` does `from run import run_deepear` and `get_type_hints(run_deepear)`
- **THEN** the hints resolve identically to before the move, since moving a function's defining module does not change its own `__annotations__`

