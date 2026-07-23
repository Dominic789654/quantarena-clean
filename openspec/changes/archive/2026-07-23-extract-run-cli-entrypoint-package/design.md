## Context

Post `extract-run-backtest-and-multipersonality-modes`, `run.py`'s only
remaining definition is `main()`. Every other name in `run.py` is
already an import from a `runner/` submodule. `main()` builds the
argparse parser, resolves the four `_*_explicit` flags, handles
`--check-env`, prints the banner, and dispatches to one of the five
mode handlers by `args.mode`.

## Goals / Non-Goals

**Goals:** move `main()` (and `DEFAULT_MULTI_PERSONALITIES_ARG`, its
sole CLI-only constant) into `runner/cli.py`; shim every internal call
whose callee is independently monkeypatched via `run.*`; collapse
`run.py` to bootstrap calls + one re-export block + the `__main__`
guard; keep every `run.<name>` re-export and `from run import <name>`
import (and the `python run.py ...` execution mode) working.

**Non-Goals:** changing argparse flags, defaults, choices, help text,
or dispatch logic; migrating any test off `run.*` import paths (that is
explicitly deferred/optional per docs/refactor_program_plan.md ground
rule 4).

## Decisions

1. **`runner/cli.py` imports every dependency directly from its owning
   `runner/` submodule, never from `run.py`.** `run.py` now imports
   `main` from `runner.cli` -- if `runner/cli.py` imported anything
   back from `run`, that would be a circular import. This mirrors how
   every other `runner/modes/*.py` file already imports its
   dependencies (`runner.env_validation`, `runner.cli_support`, etc.)
   directly rather than through `run.py`.
2. **`DEFAULT_MULTI_PERSONALITIES_ARG` moves with `main()`, not into
   `runtime_options.py`.** Unlike `DEFAULT_BACKTEST_ANALYSTS_ARG`
   (referenced by bare name inside `_resolve_backtest_runtime_options`/
   `_resolve_multi_personality_runtime_options`, both in
   `runtime_options.py`), `DEFAULT_MULTI_PERSONALITIES_ARG` has exactly
   one referencing site in the entire codebase: `main()`'s
   `--personalities` argparse default. It moves to `runner/cli.py`
   alongside its only reader; `run.py` re-exports it for the same
   reason it re-exports every other formerly-local name (grep confirms
   `test_backtest_fof_config_runtime.py` does
   `from run import (..., DEFAULT_MULTI_PERSONALITIES_ARG, ...)`).
3. **Shim scope: `print_banner` and `run_backtest_mode`, and only
   those two.** `git grep -n "monkeypatch.setattr" tests/ | grep
   "run\."` restricted to names `main()` calls shows exactly two hits
   in the context of a `main()` call:
   `test_main_marks_benchmark_cli_flags_explicit` patches
   `run.print_banner` and `run.run_backtest_mode`, then calls
   `run.main()`. No test patches `run.check_env_file`,
   `run.run_deepear`, `run.run_deepfund`, `run.run_full_pipeline`, or
   `run.run_multi_personality_mode` while calling `main()` (or at all,
   per the audits in steps 6-7) -- those five calls stay plain
   bare-name calls.
4. **`run.py`'s re-export block is fully consolidated, not
   position-preserving.** Every prior Phase 2 step kept import
   insertions at the exact source position of the removed definition,
   because other, still-present function bodies were interleaved
   between them (see `extract-run-runtime-options`'s design.md decision
   4). Once `main()` -- the last definition -- leaves, nothing remains
   in `run.py` except imports, so there is no interleaving constraint
   left to preserve. The re-export block was reorganized into one
   grouped-by-source-module sequence for readability; this is a pure
   reordering of import statements with identical net bindings, not a
   behavior change (`from X import (...)` statements have no
   interdependent ordering requirements here -- none of these modules
   import back from `run.py`).
5. **Shim call shape matches every other Phase 2 shim exactly**:
   `getattr(_shim.run_module(), "<name>", None) or <local import>`,
   assigned to a local variable immediately before the guarded call.

## Risks / Trade-offs

- None material. This is the lowest-risk step of Phase 2: `main()` has
  no other internal callers to protect (nothing calls `main()` except
  the `__main__` guard and tests), and the re-export consolidation is
  mechanical.
