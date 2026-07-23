## Context

Post `extract-run-runtime-options`, run.py's remaining top-level
functions are: `print_banner`, `run_deepear`, `run_deepfund`,
`run_full_pipeline`, `_validate_backtest_date_range`,
`_print_backtest_mode_config`, `_print_backtest_result`,
`_execute_backtest_mode`, `_print_multi_personality_config`,
`_print_multi_personality_results`, `run_backtest_mode`,
`run_multi_personality_mode`, and `main`. The plan's remaining Phase 2
steps carve this into: CLI support helpers (this change), the
deepear/deepfund/pipeline mode handlers (step 6), the backtest/
multi-personality mode handlers and their private helpers (step 7),
and `main()`/argparse (step 8).

## Goals / Non-Goals

**Goals:** identify and move every function that (a) is not itself a
mode handler and (b) is not a private helper exclusively used by a
mode handler still in scope for a later step; keep every `run.<name>`
re-export and `from run import <name>` import working.

**Non-Goals:** touching any of the mode handlers or `main()`; changing
any printed text or the `_print_backtest_result` exit-code logic.

## Decisions

1. **Scope: five pure-formatting functions.** `print_banner`,
   `_print_backtest_mode_config`, `_print_backtest_result`,
   `_print_multi_personality_config`, `_print_multi_personality_results`
   all share one shape: read already-resolved arguments/objects, print
   a formatted summary, and (only for `_print_backtest_result`) map
   `result.errors` to an exit code. None of them call another run.py
   function, build a config, select analysts/tickers, or invoke a
   backtest/multi-personality engine -- the traits that define a "mode
   handler" per the plan's step 6/7 boundary. This mirrors the ticket's
   own example ("_print_backtest_result") and extends it to the four
   siblings with the identical shape.
2. **`_validate_backtest_date_range` stays out of scope, deliberately.**
   It is a private helper, but ticket step 7 explicitly assigns it
   ("_execute_backtest_mode, run_backtest_mode, run_multi_personality_mode
   + their private helpers") to the backtest/multi-personality change,
   not this one -- and unlike the five print helpers, it makes a
   pass/fail decision that gates whether a mode handler proceeds at
   all, which puts it closer to "mode-specific logic" than pure
   presentation. It moves together with its two callers in step 7.
3. **No `_shim` needed in this change.** Every caller of the five moved
   functions (`_execute_backtest_mode`, `run_multi_personality_mode`,
   `main()`) still lives in `run.py` after this change, so their
   bare-name calls resolve against `run.py`'s own re-exported globals --
   identical to the `extract-run-runtime-options` precedent. The
   `_shim` requirement is deferred to steps 7 and 8, when those callers
   themselves leave `run.py`.
4. **Import placement mirrors removed-definition positions**, same
   pattern as `extract-run-runtime-options`: three insertion points
   (before `run_deepear`, before `_execute_backtest_mode`, before
   `run_backtest_mode`) replace the five removed definitions in place.
5. **Dropped now-unused typing imports.** `Dict` and `List` were only
   referenced by the moved functions' type hints; `run.py`'s remaining
   code only needs `Optional` (`_validate_backtest_date_range`) and
   `Any` (`_execute_backtest_mode`'s `run_backtest: Any` parameter).

## Risks / Trade-offs

- None material: the five moved functions have no cross-calls into
  each other or into any function staying in run.py, and the two with
  monkeypatch coverage (`print_banner`, `_print_backtest_result`) are
  only ever patched while their caller is still in run.py.
