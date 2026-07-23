## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "_make_cite_key\|_build_bibliography\|_render_references_section\|_inject_references\|_normalize_citations\|_clean_markdown" tests/ deepear/ backtest/ deepfund/ shared/`
  — hits in `deepear/src/agents/report_agent.py` (the six method
  definitions plus their internal `self.`/`self._`-qualified call sites
  inside `generate_report`/`_incremental_edit`); `tests/test_report_agent_citations.py`
  and `tests/test_report_agent_characterization.py` both call
  `ReportAgent._make_cite_key(url=..., title=..., source_name=...)`
  directly on the class at module import time; `tests/test_report_agent_characterization.py`
  also calls `harness.agent._clean_markdown(text)` directly on an
  instance. No test calls `_build_bibliography`,
  `_render_references_section`, `_inject_references`, or
  `_normalize_citations` directly.
- [x] 1.2 Confirm no literal `monkeypatch.setattr("...")` string path and
  no class-attribute patch of any of the six names exists anywhere in the
  repo today — none found.
- [x] 1.3 `grep -n "self\."` restricted to each of the six method bodies —
  matches only in `_build_bibliography` (`self._make_cite_key(...)`,
  `self.db.lookup_reference_by_url(...)`); zero matches in the other five,
  confirming only `_build_bibliography` needs parameter-threading (ground
  rule 6).
- [x] 1.4 Read `openspec/changes/archive/2026-07-23-fix-report-agent-citation-normalize-args/proposal.md`
  to confirm `_normalize_citations`'s three-required-argument history
  before moving it, so the move does not reintroduce a two-argument
  default.
- [x] 1.5 Verify `_clean_markdown`'s body touches no `self` state and is
  not chart-rendering-related, confirming it satisfies the plan's `ONLY
  IF` condition for inclusion in this step rather than deferral.
- [x] 1.6 Confirm `_clean_ticker`/`_signal_mentions_ticker` (step 28) and
  all chart-rendering code (step 29) are left untouched.

## 2. Implementation

- [x] 2.1 Create `deepear/src/agents/report/citations.py`: move
  `_make_cite_key`, `_build_bibliography` (threading `self.db` as an
  explicit required keyword-only `db` parameter on
  `build_bibliography(signals, *, db)`, and rewriting its
  `self._make_cite_key(...)` call to a direct in-module
  `make_cite_key(...)` call), `_render_references_section`,
  `_inject_references`, `_normalize_citations` (including its nested
  `repl_legacy`/`repl_key`/`repl_loose_key` closures), and
  `_clean_markdown`'s bodies verbatim into module-level functions.
- [x] 2.2 `report_agent.py`: add `from deepear.src.agents.report.citations
  import (make_cite_key, build_bibliography, render_references_section,
  inject_references, normalize_citations, clean_markdown)` (aliased on
  import to avoid name collision with the existing method names, matching
  `structured_report.py`'s aliasing convention); replace each of the six
  method bodies with a one-line delegator, preserving each method's
  original binding kind (`@staticmethod` for four of them; bound instance
  method for `_build_bibliography` and `_clean_markdown`).

## 3. Tests

- [x] 3.1 Add `tests/test_report_citations_module.py`: direct
  `make_cite_key` coverage (stability/dedup, url-priority, fallback
  basis); direct `build_bibliography` coverage against a small scripted
  signal list using `tests/report_agent_harness.py`'s
  `FakeDatabaseManager` (cross-signal dedup, db-lookup-wins,
  lookup-miss-falls-back, no-citable-fields-is-skipped, raw-dict
  single-source branch); `render_references_section` +
  `inject_references` round-trip coverage (empty bibliography, append
  path, replace-in-place path); `normalize_citations` coverage for the
  legacy `[[n]]` marker and the loose ASCII/fullwidth paren-wrapped marker
  forms (not already pinned by `test_report_agent_citations.py`, which
  only exercises the `[@KEY]` bracket form); `clean_markdown` direct
  coverage; and a delegation-identity test per moved `ReportAgent`
  attribute proving its output matches the module function's output on
  the same inputs.
- [x] 3.2 Confirm `tests/test_report_agent_citations.py` (1 test),
  `tests/test_report_agent_characterization.py` (22 tests),
  `tests/test_report_retry_helper.py` (7 tests), and
  `tests/test_report_pure_functions.py` (24 tests) all still pass
  unchanged.

## 4. Gates

- [x] 4.1 `ruff check .` clean.
- [x] 4.2 `rtk proxy python -m pytest tests/test_report_citations_module.py tests/test_report_agent_citations.py tests/test_report_agent_characterization.py tests/test_report_retry_helper.py tests/test_report_pure_functions.py -q`
  — 78 passed (24 new + 54 pre-existing).
- [x] 4.3 `rtk proxy python -m pytest tests/ -q` — 1022 passed (998
  baseline + 24 new), 10 skipped, 0 failed.
- [x] 4.4 `openspec validate --changes` passes.
- [x] 4.5 `python -W error::SyntaxWarning -c "import deepear.src.agents.report.citations; import deepear.src.agents.report_agent"`
  — no warning raised.
