## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "sanitize_json_chart_blocks\|build_structured_report" tests/ deepear/ backtest/ deepfund/ shared/`
  — hits (before this change) in `deepear/src/agents/report_agent.py` (the
  two method definitions plus their two internal `self.`-qualified call
  sites inside `generate_report`) and
  `tests/test_report_agent_characterization.py` (three direct
  `ReportAgent._sanitize_json_chart_blocks(text)` calls, one comment
  mentioning `build_structured_report`, no call and no monkeypatch of
  either name).
- [x] 1.2 Confirm no literal `monkeypatch.setattr("...")` string path and no
  class-attribute patch of either name exists anywhere in the repo today
  — none found.
- [x] 1.3 `grep -n "self\." ` restricted to each method's body — zero
  matches for both `_sanitize_json_chart_blocks` and
  `build_structured_report`, confirming neither needs parameter-threading
  (ground rule 6 is vacuous here).
- [x] 1.4 Confirm `_clean_markdown` (~line 991), `_make_cite_key`,
  `_render_references_section`, `_inject_references` are left untouched
  (they belong to step 27, `extract-report-agent-citation-manager`).

## 2. Implementation

- [x] 2.1 Create `deepear/src/agents/report/chart_sanitizer.py`: move
  `_sanitize_json_chart_blocks`'s body (including the nested
  `find_json_end` helper) verbatim into module-level
  `sanitize_json_chart_blocks(text)`.
- [x] 2.2 Create `deepear/src/agents/report/structured_report.py`: move
  `build_structured_report`'s body verbatim into module-level
  `build_structured_report(report_md, signals, clusters)`.
- [x] 2.3 `report_agent.py`: add `from deepear.src.agents.report
  .chart_sanitizer import sanitize_json_chart_blocks` and `from
  deepear.src.agents.report.structured_report import
  build_structured_report as _build_structured_report_impl`; replace both
  staticmethod bodies with one-line delegators.

## 3. Tests

- [x] 3.1 Add `tests/test_report_pure_functions.py`: direct
  `sanitize_json_chart_blocks` coverage of fence-normalization variants not
  already pinned by the characterization suite, plus the empty-string and
  no-fence-marker short-circuits.
- [x] 3.2 Same file: direct `build_structured_report` coverage of title
  extraction/default, implicit leading "摘要" section, bullet-marker
  recognition and the 8-item cap, dict-vs-attribute signal access, missing
  optional-field defaults, cluster-to-signal-id mapping (including ids
  absent from the signal map), and the empty-input default shape.
- [x] 3.3 Same file: delegation-regression tests proving
  `ReportAgent._sanitize_json_chart_blocks` and both a real
  `ReportAgent` instance's and the class's `build_structured_report`
  produce identical output to the module functions on the same input.
- [x] 3.4 Confirm `tests/test_report_agent_characterization.py` (22 tests)
  still passes unchanged.

## 4. Gates

- [x] 4.1 `ruff check .` clean.
- [x] 4.2 `rtk proxy python -m pytest tests/test_report_pure_functions.py tests/test_report_agent_characterization.py -q`
  — 46 passed (24 new + 22 characterization).
- [x] 4.3 `rtk proxy python -m pytest tests/ -q` — 998 passed (974 baseline
  + 24 new), 10 skipped, 0 failed.
- [x] 4.4 `openspec validate --changes` passes.
