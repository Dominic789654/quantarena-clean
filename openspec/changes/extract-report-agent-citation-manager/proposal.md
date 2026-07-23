## Why

Phase 4 step 27 (docs/refactor_program_plan.md). Steps 24-26 landed the
characterization harness (`tests/report_agent_harness.py`,
`tests/test_report_agent_characterization.py`, 22 tests) and two leaf
modules, `deepear/src/agents/report/retry.py` and
`deepear/src/agents/report/chart_sanitizer.py` /
`deepear/src/agents/report/structured_report.py`, out of
`deepear/src/agents/report_agent.py`'s `ReportAgent` class. This step
extracts the citation/bibliography machinery -- `_make_cite_key`,
`_build_bibliography`, `_render_references_section`, `_inject_references`,
`_normalize_citations`, and `_clean_markdown` -- into a new module,
`deepear/src/agents/report/citations.py`. `tests/test_report_agent_citations.py`
already pins the Phase 0 bug fix
(`openspec/changes/archive/2026-07-23-fix-report-agent-citation-normalize-args/`)
that made `_normalize_citations` require all three of its arguments; this
move must not regress it.

## What Changes

- Add `deepear/src/agents/report/citations.py` exposing six module-level
  functions: `make_cite_key(url, title="", source_name="")`,
  `build_bibliography(signals, *, db)`, `render_references_section
  (bib_entries, key_to_num)`, `inject_references(report_md, references_md)`,
  `normalize_citations(report_md, signal_to_keys, key_to_num)` (including its
  nested `repl_legacy`/`repl_key`/`repl_loose_key` closures), and
  `clean_markdown(text)` -- all six method bodies moved verbatim.
- Of the six, only `_build_bibliography` touched instance state: it read
  `self._make_cite_key(...)` (now a direct in-module call, since both
  functions live together) and `self.db.lookup_reference_by_url(url)`. Per
  ground rule 6, the `self.db` read becomes an explicit required
  keyword-only `db` parameter. `_clean_markdown` is included in this move
  too: `grep -n "self\."` on its body finds zero matches (it never reads or
  writes `self` despite being defined as an instance method) and it is
  markdown-cleanup glue with no chart-rendering behavior, so it satisfies
  the plan's `ONLY IF` condition for moving it alongside citations rather
  than deferring it.
- `ReportAgent` keeps all six as real attributes of their original binding
  kind: `_make_cite_key`/`_render_references_section`/`_inject_references`/
  `_normalize_citations` stay staticmethods; `_build_bibliography` and
  `_clean_markdown` stay bound instance methods (the former because it now
  must forward `self.db`; the latter to preserve its existing `self.
  _clean_markdown(...)` call spelling even though it needs no instance
  state). Each is a one-line delegator to the corresponding module function,
  not a bare attribute alias.
- Add `tests/test_report_citations_module.py`: direct coverage of
  `make_cite_key` (stability/dedup), `build_bibliography` (scripted signal
  list plus the newly-threaded `db` dependency, via
  `tests/report_agent_harness.py`'s `FakeDatabaseManager`),
  `render_references_section` + `inject_references` (round-trip, both the
  replace-existing-section and append-when-absent paths),
  `normalize_citations` scenarios not already pinned elsewhere (the legacy
  `[[n]]` marker and the loose `（@KEY）`/`(@KEY)` paren-wrapped marker --
  the `[@KEY]` bracket form is already pinned by
  `tests/test_report_agent_citations.py`), and a delegation-identity test
  per moved attribute proving `ReportAgent.<name>(...)` output is identical
  to the module function's output on the same inputs.
- No behavior change. `tests/test_report_agent_citations.py`,
  `tests/test_report_agent_characterization.py`,
  `tests/test_report_retry_helper.py`, and `tests/test_report_pure_functions.py`
  are left completely unmodified and must keep passing unchanged.

## Capabilities

### New Capabilities
- `report-agent-citation-manager`: the standalone citation-key derivation,
  bibliography construction, references rendering/injection, and citation-
  marker normalization functions used by `ReportAgent` to turn source
  attributions into a numbered, anchored "## 参考文献" section.

### Modified Capabilities
- None.

## Impact

- New files: `deepear/src/agents/report/citations.py`,
  `tests/test_report_citations_module.py`.
- Modified: `deepear/src/agents/report_agent.py` (one new fully-qualified
  import block; six method bodies replaced by one-line delegators).
- Monkeypatch audit (ground rule 2): `git grep -n
  "_make_cite_key\|_build_bibliography\|_render_references_section\|
  _inject_references\|_normalize_citations\|_clean_markdown" tests/
  deepear/ backtest/ deepfund/ shared/` shows: the six method definitions
  and their internal `self.`/`self._`-qualified call sites inside
  `deepear/src/agents/report_agent.py`'s `generate_report` /
  `_incremental_edit`; `tests/test_report_agent_citations.py` and
  `tests/test_report_agent_characterization.py` both call
  `ReportAgent._make_cite_key(url=..., title=..., source_name=...)` directly
  on the *class* (not an instance) at module import time to derive
  deterministic fixture cite keys, and
  `tests/test_report_agent_characterization.py` also calls
  `harness.agent._clean_markdown(text)` directly on an *instance*. No test
  calls `_build_bibliography`, `_render_references_section`,
  `_inject_references`, or `_normalize_citations` directly -- all four are
  only exercised indirectly through a real `generate_report` run. No
  literal `monkeypatch.setattr("...")` string path and no class-attribute
  patch of any of the six names exists anywhere in the repo today.
  `ReportAgent` keeps every one of the six as a real attribute of its
  original binding kind (not a bare attribute alias) specifically so a
  future class-attribute or instance-attribute monkeypatch of any of the
  names -- and the existing class-level `ReportAgent._make_cite_key(...)`
  calls -- keep working exactly as before.
