## Context

`run.py` (post `extract-run-config-discovery`) defines
`_extract_market_from_config`, `_extract_tickers_from_config`,
`_resolve_backtest_runtime_options`, `_resolve_multi_personality_runtime_options`
together, then, further down (interleaved with
`_validate_backtest_date_range`, `_print_backtest_mode_config`, and other
mode-handler code out of scope for this step), `VALID_PERSONALITIES`,
`_parse_tickers_arg`, `_parse_optional_csv`, and `_parse_personalities_arg`.
`DEFAULT_BACKTEST_ANALYSTS_ARG` is a module-level constant set at
`run.py`'s top (alongside `PROJECT_ROOT`/`DEEPFUND_SRC`).

Both resolvers call `_select_backtest_config_file` and
`_load_yaml_config_file` (already moved to `runner/config_discovery.py`
by the prior change) and reference `DEFAULT_BACKTEST_ANALYSTS_ARG` by
bare name; `_resolve_multi_personality_runtime_options` additionally
calls `_parse_personalities_arg`, which references `VALID_PERSONALITIES`
by bare name.

## Goals / Non-Goals

**Goals:** move the two resolvers and every private helper used only by
them; keep every `run.<name>` re-export and `from run import <name>`
import working; resolve the two module-global constant dependencies
without a monkeypatch break or a `NameError`.

**Non-Goals:** touching `_validate_backtest_date_range`,
`_print_backtest_mode_config`/`_print_multi_personality_config`,
`_execute_backtest_mode`, `run_backtest_mode`,
`run_multi_personality_mode`, or `main()` — all stay in `run.py`,
slated for later Phase 2 steps (mode handlers / CLI entrypoint).

## Decisions

1. **Helper scope beyond the plan's example list.** The plan's scope
   guidance names `_extract_tickers_from_config`, `_parse_tickers_arg`,
   `_extract_market_from_config`, `_parse_optional_csv` as "e.g." (an
   illustrative, not exhaustive, list) and says to verify with grep who
   else uses them. `_parse_personalities_arg` is not in that list but is
   called *only* by `_resolve_multi_personality_runtime_options` (`git
   grep -n _parse_personalities_arg run.py` shows one caller, one
   definition). It moves too — leaving it behind would make the moved
   resolver's bare-name call `_parse_personalities_arg(...)` resolve
   against `runner.runtime_options`'s own globals (where it wouldn't
   exist), raising `NameError` at call time. This is a harder failure
   mode than the monkeypatch-breaking trap ground rule 3 describes (a
   silent test blind-spot); either way, the fix is the same: move the
   callee with its only caller.
2. **Constants must move with their bare-name referents, for the same
   reason.** `DEFAULT_BACKTEST_ANALYSTS_ARG` is read by bare name inside
   both resolvers; `VALID_PERSONALITIES` is read by bare name inside
   `_parse_personalities_arg`. Both constants move into
   `runner/runtime_options.py`, and `run.py` re-exports them — this
   mirrors the `extract-run-config-discovery` precedent (that change
   substituted `get_project_root()` for the out-of-scope `PROJECT_ROOT`
   global instead of duplicating a value; here the constants have no
   equivalent "call the source of truth" option since they're literals
   / derived-once values, so relocating the single definition is the
   analogous move). No test monkeypatches either constant, so this is
   safe; `run.py`'s own `main()` (which uses
   `default=DEFAULT_BACKTEST_ANALYSTS_ARG` and
   `choices=VALID_PERSONALITIES` in its argparse setup) is unaffected —
   it reads the re-exported module attribute exactly as it read the
   local definition before.
3. **No `_shim` needed yet.** No monkeypatch string touches any of the
   seven moved functions or two constants (verified by grep — see
   proposal.md). `_shim` is deferred to change 4, where it becomes
   mandatory for `_validate_backtest_environment_for_runtime` /
   `_validate_environment`.
4. **Import placement mirrors removed-definition positions.** Because
   non-moving functions are interleaved with the moved ones in `run.py`'s
   source order, the single-block "delete + one import" pattern used in
   changes 1–2 isn't available; instead each contiguous run of moved
   definitions is replaced by an import statement at that same position
   (four insertion points total), keeping the diff auditable per
   original location rather than hoisting everything to the top.

## Risks / Trade-offs

- None material: zero monkeypatch coverage on any moved name; the
  constant relocation is a definition move, not a value change.
