# report-agent-signal-clusterer Specification

## Purpose
TBD - created by archiving change extract-report-agent-signal-clusterer. Update Purpose after archive.
## Requirements
### Requirement: cluster_signals groups signals into named themes via a shared planner instance
`deepear.src.agents.report.clustering.cluster_signals(signals, user_query=None, *, planner)` SHALL build a numbered preview string of each signal's `title` (via attribute access for non-dict signals, via `.get("title", "")` for dict signals), SHALL build the planner instruction from that preview and `user_query` via `get_cluster_planner_instructions`, SHALL assign `planner.instructions = [instruction]` on the caller-supplied `planner` object before calling it, SHALL call `planner.run(get_cluster_task(preview))` on that same object and parse its `.content` via `extract_json`, SHALL return the parsed `"clusters"` list when present, and SHALL return `[]` (logging instead of raising) both when the parsed JSON has no `"clusters"` key and when `planner.run(...)` or JSON parsing raises any exception.

#### Scenario: A well-formed clustering response yields the parsed clusters list
- **WHEN** `cluster_signals(signals, user_query="q", planner=planner)` is called and `planner.run(...)` returns a response whose `.content` is `'{"clusters": [{"theme_title": "T", "signal_ids": [1, 2]}]}'`
- **THEN** it returns `[{"theme_title": "T", "signal_ids": [1, 2]}]`

#### Scenario: Unparsable JSON falls back to an empty list
- **WHEN** `cluster_signals(signals, user_query=None, planner=planner)` is called and `planner.run(...)` returns a response whose `.content` is not valid JSON containing a `"clusters"` key
- **THEN** it returns `[]`

#### Scenario: An exception raised while calling the planner falls back to an empty list
- **WHEN** `cluster_signals(signals, user_query=None, planner=planner)` is called and `planner.run(...)` raises an exception
- **THEN** it returns `[]` without propagating the exception

#### Scenario: Signal title access works for both dict and attribute-style signals
- **WHEN** `cluster_signals` builds its numbered preview over a mix of dict signals (read via `.get("title", "")`) and attribute-style signals (read via `.title`)
- **THEN** the preview line for each signal reflects that signal's own `title` regardless of its access style

### Requirement: cluster_signals shares the caller-supplied planner instance by reference, not a copy
`cluster_signals` SHALL NOT construct, copy, or wrap a new `Agent`-like object in place of its `planner` parameter, SHALL read and mutate the exact object passed in as `planner` (its `.instructions` assignment and its `.run(...)` call both target that same object), and SHALL require `planner` as a keyword-only argument with no default so no call site can silently omit sharing the caller's own instance.

#### Scenario: The object the planner.run call is issued against is the exact object the caller passed in
- **WHEN** a recording fake planner object is passed as `cluster_signals(signals, user_query=None, planner=recording_planner)`
- **THEN** the object recorded as having received the `.run(...)` call `is` (identity, not equality) `recording_planner`

#### Scenario: ReportAgent forwards its own self.planner by reference into the module function
- **WHEN** a real `ReportAgent` instance's `_cluster_signals(signals, user_query)` delegator is called
- **THEN** the `planner` object the underlying `cluster_signals` call receives `is` (identity, not equality) that same `ReportAgent` instance's `self.planner` attribute

### Requirement: ReportAgent keeps a real bound-method delegator for _cluster_signals
`ReportAgent._cluster_signals(self, signals, user_query=None)` SHALL remain a real bound instance method returning `deepear.src.agents.report.clustering.cluster_signals(signals, user_query, planner=self.planner)`'s result unchanged, such that `_cluster_signals` remains patchable as a class attribute or instance attribute and every internal call site inside `generate_report` is intercepted by such a patch.

#### Scenario: The delegator produces output identical to the module function given the same planner
- **WHEN** `ReportAgent._cluster_signals(signals, user_query)` is called on a real instance, and separately `cluster_signals(signals, user_query, planner=<that same instance's self.planner>)` is called directly
- **THEN** both calls return deep-equal results

#### Scenario: generate_report's internal call site keeps working unchanged
- **WHEN** `ReportAgent.generate_report` runs its clustering phase
- **THEN** it observes the exact same clusters list `_cluster_signals` returned before this change, for the same scripted planner response

