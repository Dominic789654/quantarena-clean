## Why

`ReportAgent._normalize_citations(report_md, signal_to_keys, key_to_num)` takes three required arguments, but the non-incremental report path calls it with only two (`deepear/src/agents/report_agent.py:970`), so any `ReportAgent(..., incremental_edit=False)` run whose joined section length stays under the 80k-char incremental threshold raises `TypeError` at final assembly. The bug is dormant only because no test constructs a real `ReportAgent`; it was surfaced by the refactor-program planning analysis (docs/refactor_program_plan.md).

## What Changes

- Fix the call at `report_agent.py:970` to pass `key_to_num` (matching the correct call sites at lines 999 and 1204).
- Add a regression test that constructs a real `ReportAgent` with stub model/DB, runs `generate_report` down the non-incremental branch, and asserts citation normalization completes. This is also the first seed of the characterization harness required by the report-agent decomposition track.
- No behavior change on the incremental path.

## Capabilities

### New Capabilities
- None (bug fix within existing behavior).

### Modified Capabilities
- None (no spec-level requirement changes; the intended behavior was always "normalize citations with the key-to-number map").

## Impact

- `deepear/src/agents/report_agent.py`: one-line call fix.
- `tests/`: new regression test with minimal `FakeAgent`/`FakeModel`/`FakeDatabaseManager` stubs (reusable by the later decomposition track).
