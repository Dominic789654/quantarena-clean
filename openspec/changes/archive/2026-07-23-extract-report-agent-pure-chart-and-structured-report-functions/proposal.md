## Why

Phase 4 step 26 (docs/refactor_program_plan.md). Step 25
(`extract-report-agent-retry-helper`) landed the package shape
(`deepear/src/agents/report/__init__.py`, `retry.py`) and the delegator
pattern this step follows. This step extracts the two functions on
`ReportAgent` (`deepear/src/agents/report_agent.py`, 1634 lines) that touch
no instance/class state at all -- `_sanitize_json_chart_blocks` (a
staticmethod repairing malformed ```` ```json-chart ```` fenced blocks,
including its nested `find_json_end` helper) and `build_structured_report`
(a staticmethod turning the final markdown report into a JSON-shaped object
for frontend rendering) -- into two new leaf modules,
`deepear/src/agents/report/chart_sanitizer.py` and
`deepear/src/agents/report/structured_report.py`.
`tests/test_report_agent_characterization.py`'s
`TestCleanMarkdownAndSanitize` (3 scenarios) and the structured-report
assertions inside `TestGenerateReportIncrementalHappyPath` already pin
current behavior for both.

## What Changes

- Add `deepear/src/agents/report/chart_sanitizer.py` exposing
  `sanitize_json_chart_blocks(text)`, `_sanitize_json_chart_blocks`'s body
  moved verbatim (including the nested `find_json_end` closure). `grep -n
  "self\." ` restricted to the original staticmethod body finds zero
  matches, so no parameter-threading was needed -- the signature is
  unchanged apart from dropping `@staticmethod` and the leading underscore.
- Add `deepear/src/agents/report/structured_report.py` exposing
  `build_structured_report(report_md, signals, clusters)`,
  `ReportAgent.build_structured_report`'s body moved verbatim. Same result:
  zero `self.` references in the original body, so no threading needed.
- `ReportAgent._sanitize_json_chart_blocks` and
  `ReportAgent.build_structured_report` stay real staticmethods on the
  class, each reduced to a one-line delegator to the corresponding module
  function (the latter imported under an alias,
  `build_structured_report as _build_structured_report_impl`, to avoid
  shadowing the class attribute of the same name). Both of
  `report_agent.py`'s internal call sites
  (`self._sanitize_json_chart_blocks(...)` and
  `self.build_structured_report(...)` inside `generate_report`) keep
  calling through `self.` unchanged.
- Add `tests/test_report_pure_functions.py`: direct coverage of
  `sanitize_json_chart_blocks`'s fence-normalization variants not already
  pinned by the characterization suite (double-backtick fences, fence/
  language split across lines, fence at the end of a content line, closing
  fence on the same line as the JSON object, back-to-back well-formed
  blocks, an unrepairable unbalanced-brace block, and the empty-string/
  no-marker-at-all short-circuits), direct coverage of
  `build_structured_report`'s field mapping (title extraction/default,
  implicit leading "摘要" section, bullet-marker recognition and the 8-item
  cap, dict-vs-attribute signal access, missing-field defaults, cluster-to-
  signal-id mapping including ids absent from the signal map, and the
  empty-input default shape), and a delegation-regression suite proving
  `ReportAgent._sanitize_json_chart_blocks` / a real
  `ReportAgent().build_structured_report(...)` / `ReportAgent
  .build_structured_report(...)` produce byte-identical output to the
  module functions on the same input.
- No behavior change. `tests/test_report_agent_characterization.py` is left
  completely unmodified and must keep passing unchanged (22 tests).

## Capabilities

### New Capabilities
- `report-agent-pure-functions`: the two standalone, self-state-free
  functions `ReportAgent` uses to (a) repair malformed
  ```` ```json-chart ```` fences before chart processing and (b) shape its
  final markdown output into a structured JSON object for the frontend.

### Modified Capabilities
- None.

## Impact

- New files: `deepear/src/agents/report/chart_sanitizer.py`,
  `deepear/src/agents/report/structured_report.py`,
  `tests/test_report_pure_functions.py`.
- Modified: `deepear/src/agents/report_agent.py` (two new fully-qualified
  imports; `_sanitize_json_chart_blocks` and `build_structured_report`
  bodies each replaced by a one-line delegator).
- Monkeypatch audit (ground rule 2): `git grep -n
  "sanitize_json_chart_blocks\|build_structured_report" tests/ deepear/
  backtest/ deepfund/ shared/` shows exactly four hits outside this
  change's own new files: `deepear/src/agents/report_agent.py` (the two
  method definitions plus their two internal `self.`-qualified call sites
  inside `generate_report`), and `tests/test_report_agent_characterization
  .py` (three direct `ReportAgent._sanitize_json_chart_blocks(text)` calls
  and one comment mentioning `build_structured_report` -- no call, no
  monkeypatch of either name). No literal `monkeypatch.setattr("...")`
  string path and no class-attribute patch of either name exists anywhere
  in the repo today. `ReportAgent` keeps both as real staticmethods (not
  bare attribute aliases) specifically so a future
  `monkeypatch.setattr(ReportAgent, "_sanitize_json_chart_blocks", ...)` or
  `monkeypatch.setattr(ReportAgent, "build_structured_report", ...)`
  class-attribute patch would still intercept the corresponding internal
  `self.`-qualified call site inside `generate_report`.
