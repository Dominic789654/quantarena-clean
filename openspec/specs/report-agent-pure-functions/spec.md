# report-agent-pure-functions Specification

## Purpose
TBD - created by archiving change extract-report-agent-pure-chart-and-structured-report-functions. Update Purpose after archive.
## Requirements
### Requirement: sanitize_json_chart_blocks is a pure function repairing malformed json-chart fences
`deepear.src.agents.report.chart_sanitizer.sanitize_json_chart_blocks(text)` SHALL return `text` unchanged when it is empty/falsy, SHALL (when `"json-chart"` appears anywhere in `text`) first normalize known opening-fence typo variants (```` ``json-chart ````, ```` ``` json-chart ````, ```` `` json-chart ````, a bare ```` ``` ```` or ```` `` ```` fence line immediately followed by a `json-chart` line, and an opening fence appearing at the end of a content line immediately followed by a `json-chart` line) to a canonical ```` ```json-chart ```` opening line and known closing-fence typo variants (a bare ```` `` ```` line, or a closing fence appearing mid-line after the JSON object) to a canonical ```` ``` ```` closing line, rejoining all lines with `"\n".join` (which drops a trailing newline if the original text ended with one), and SHALL then (only if a ```` ```json-chart ```` opening fence is present after normalization) scan forward from each such opening fence, locate the first JSON object via balanced-brace matching that ignores braces inside quoted strings, and insert a closing ```` ``` ```` fence immediately after that JSON object unless a closing fence already appears before the next opening fence, leaving text after an unrepairable (unbalanced-brace) JSON object untouched.

#### Scenario: Empty input is returned unchanged
- **WHEN** `sanitize_json_chart_blocks("")` is called
- **THEN** it returns `""`

#### Scenario: Well-formed block is preserved except for the trailing-newline-drop quirk
- **WHEN** `text` is a single well-formed ```` ```json-chart ```` block with no trailing newline
- **THEN** `sanitize_json_chart_blocks(text)` returns `text` unchanged

#### Scenario: Double-backtick and split-line opening fence variants are normalized and repaired
- **WHEN** `text` contains an opening fence written as ` ``json-chart `, or as a bare fence line followed by a `json-chart` line, or as an opening fence at the end of a content line followed by a `json-chart` line, each followed by a JSON object with no closing fence
- **THEN** `sanitize_json_chart_blocks(text)` produces a canonical ```` ```json-chart ```` opening line and inserts a canonical ```` ``` ```` closing fence right after the JSON object, preserving any trailing prose outside the repaired block

#### Scenario: Bare double-backtick closing fence is normalized
- **WHEN** `text` contains a well-formed ```` ```json-chart ```` block whose closing fence is written as a bare ` `` ` line
- **THEN** `sanitize_json_chart_blocks(text)` rewrites that closing fence to ```` ``` ````

#### Scenario: Back-to-back well-formed blocks are left as-is
- **WHEN** `text` contains two well-formed ```` ```json-chart ```` blocks in sequence, each already properly closed
- **THEN** `sanitize_json_chart_blocks(text)` returns `text` unchanged (aside from the trailing-newline-drop quirk)

#### Scenario: Unbalanced-brace JSON object is left unrepaired
- **WHEN** an opening ```` ```json-chart ```` fence is followed by a JSON object whose braces never balance before the text ends
- **THEN** `sanitize_json_chart_blocks(text)` leaves the remainder of `text` from the opening fence onward untouched rather than guessing where to insert a closing fence

### Requirement: build_structured_report is a pure function shaping a markdown report into a JSON-renderable object
`deepear.src.agents.report.structured_report.build_structured_report(report_md, signals, clusters)` SHALL return a dict with keys `title` (the first line starting with `"# "` with that prefix stripped, defaulting to `"研报"` if no such line exists), `summary_bullets` (up to 8 lines starting with `"- "`, `"* "`, or `"• "` with that marker stripped, in document order), `sections` (a list of `{"title", "content"}` dicts split on `#{2,4}` headings, with any content preceding the first heading collected into an implicit leading section titled `"摘要"`), `clusters` (for each entry in `clusters or []`, a dict with `title` from `theme_title`, `rationale` from `rationale`, `signal_ids` from `signal_ids`, and `signals` being the subset of those ids' corresponding `signal_map` entries that exist), and `signals` (a list of one dict per input signal, 1-indexed by `id`, with `title`/`summary`/`sentiment_score`/`confidence`/`intensity`/`impact_tickers`/`expected_horizon` read via `.get(...)` for dict signals or via `hasattr`/`getattr` (with the same field-specific defaults) for non-dict signals).

#### Scenario: Empty report_md yields the default shape
- **WHEN** `build_structured_report("", signals=[], clusters=[])` is called
- **THEN** it returns the default `title` `"研报"`, empty `sections`, empty `summary_bullets`, empty `signals`, and empty `clusters`

#### Scenario: Title is taken from the first level-1 heading
- **WHEN** `report_md` contains a line `"# My Report Title"`
- **THEN** the returned dict's `title` is `"My Report Title"`

#### Scenario: Dict and attribute-style signals are both mapped correctly
- **WHEN** `signals` contains a plain dict with `title`/`summary`/etc. keys and, in a separate call, an object exposing the same fields as attributes
- **THEN** `build_structured_report` produces an identical `signals` entry shape for both, reading dict signals via `.get(...)` and non-dict signals via `hasattr`/`getattr`

#### Scenario: Cluster signal_ids absent from the signal map are kept in signal_ids but dropped from signals
- **WHEN** a cluster's `signal_ids` includes an id with no corresponding entry in `signal_map` (e.g. out of range for the `signals` list)
- **THEN** the returned cluster's `signal_ids` list still includes that id, but its `signals` list omits the missing entry

### Requirement: ReportAgent keeps real staticmethod delegators for both pure functions
`ReportAgent._sanitize_json_chart_blocks(text)` SHALL remain a real staticmethod on the class (not a bare attribute alias) that returns `deepear.src.agents.report.chart_sanitizer.sanitize_json_chart_blocks(text)`, and `ReportAgent.build_structured_report(report_md, signals, clusters)` SHALL remain a real staticmethod on the class (not a bare attribute alias) that returns `deepear.src.agents.report.structured_report.build_structured_report(report_md, signals, clusters)`, such that both remain patchable as class attributes and every internal `self._sanitize_json_chart_blocks(...)` / `self.build_structured_report(...)` call site inside `generate_report` is intercepted by such a patch.

#### Scenario: Delegators produce identical output to the module functions
- **WHEN** `ReportAgent._sanitize_json_chart_blocks(text)` and `sanitize_json_chart_blocks(text)` are called with the same `text`, and `ReportAgent.build_structured_report(report_md, signals, clusters)` / a real `ReportAgent` instance's `build_structured_report(report_md, signals, clusters)` and `build_structured_report(report_md, signals, clusters)` are called with the same arguments
- **THEN** each pair returns byte-identical/deep-equal results

#### Scenario: Class-attribute patch intercepts the internal generate_report call sites
- **WHEN** `ReportAgent._sanitize_json_chart_blocks` or `ReportAgent.build_structured_report` is patched as a class attribute
- **THEN** the patched behavior is used by the corresponding internal `self.`-qualified call site inside `generate_report`

