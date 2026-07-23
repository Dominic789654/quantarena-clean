## Context

`_normalize_citations` (report_agent.py:260) is a static method requiring `(report_md, signal_to_keys, key_to_num)`. Three call sites exist: line 970 (non-incremental final assembly — passes 2 args, broken), line 999 (incremental path — correct), line 1204 (section path — correct). The non-incremental branch executes when `incremental_edit=False` and total joined section length ≤ 80000 chars (report_agent.py:917).

## Goals / Non-Goals

**Goals:** fix the TypeError; pin the non-incremental branch with the first real `ReportAgent` test.

**Non-Goals:** any structural extraction (that is the `report_agent` decomposition track); testing LLM output quality.

## Decisions

1. Minimal fix: add `key_to_num` to the line-970 call — identical semantics to the two correct call sites, no signature change.
2. The regression test builds stubs directly (FakeModel with `id`, FakeAgent whose `run()` returns canned section text, in-memory FakeDatabaseManager) rather than importing test_deepear_workflow's dummy (which replaces ReportAgent entirely and would defeat the purpose). Stubs live in the test module for now; the decomposition track will promote them to a shared fixture.
3. Keep the test signals tiny (2 signals, short sections) to stay under the 80k threshold deterministically.

## Risks / Trade-offs

- ReportAgent's constructor builds several agno Agents; the test must stub `agno.agent.Agent` interactions without the sys.modules pollution pattern that plagued older deepear tests — use monkeypatch-scoped attribute patching, not module replacement.
