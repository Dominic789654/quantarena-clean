## Context

Day-shared multi-personality reports export `daily_decisions.jsonl` by reading each decision's `_applied` metadata. Most specialized execution paths set `_applied` explicitly, but Smart Beta decisions are produced without that field and then executed by the base engine, so the exported rows currently show `applied=null`.

## Goals / Non-Goals

**Goals:**

- Ensure Smart Beta daily decision exports contain explicit boolean `applied` values.
- Preserve the current execution flow where Smart Beta decisions are not pre-applied and are executed by the base engine.
- Keep daily decision artifact consumers from needing personality-specific null handling.

**Non-Goals:**

- Change Smart Beta allocation, optimization, trade sizing, or benchmark behavior.
- Change existing already-applied LLM/specialized execution paths.
- Rewrite the daily decision artifact schema.

## Decisions

- Set `_applied=False` when Smart Beta emits BUY/SELL/HOLD decisions. This records that the decision still needs the normal execution path, matching the base engine contract.
- Do not coerce missing `_applied` to `False` in the report exporter. Exporting should preserve upstream metadata and tests should catch missing execution-state metadata at the source.
- Add a focused Smart Beta unit test and a report-normalization regression test so both the producer and exported artifact behavior are covered.

## Risks / Trade-offs

- [Risk] Marking `_applied=False` might look like "not executed" after the day finishes. -> Mitigation: this project already uses `_applied` to mean "pre-applied before `_execute_day_with_decisions`"; `False` is the correct source-state for Smart Beta decisions.
- [Risk] Existing rows from older reports still contain nulls. -> Mitigation: this is a forward fix; historical report files are not rewritten.

## Migration Plan

No migration is needed. New Smart Beta runs will emit explicit `_applied=False` metadata and new multi-personality reports will export `applied=false` for Smart Beta daily decisions.
