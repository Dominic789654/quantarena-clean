# report-agent-characterization Specification

## Purpose
TBD - created by archiving change build-report-agent-characterization-harness. Update Purpose after archive.
## Requirements
### Requirement: ReportAgent construction wires collaborators without eagerly loading the forecast pipeline
`ReportAgent.__init__(db, model, incremental_edit=True, tool_model=None)` SHALL store `db`, `model`, and `incremental_edit` as given, SHALL default `tool_model` to `model` when `tool_model` is omitted, SHALL construct its `planner` agent with `output_schema=ClusterContext` if and only if `hasattr(self.tool_model, 'response_format')` is true, and SHALL leave `self._forecast_agent` as `None` (never constructing a `ForecastAgent`) purely as a result of construction.

#### Scenario: incremental_edit flag is honored for both values
- **WHEN** `ReportAgent(db, model, incremental_edit=True)` and `ReportAgent(db, model, incremental_edit=False)` are each constructed
- **THEN** the resulting instances' `.incremental_edit` attributes are `True` and `False` respectively

#### Scenario: tool_model defaults to model when omitted
- **WHEN** `ReportAgent(db, model)` is constructed without a `tool_model` argument
- **THEN** the resulting instance's `.tool_model` is the same object as `.model`

#### Scenario: planner output_schema is gated by tool_model.response_format
- **WHEN** `ReportAgent` is constructed with a `tool_model` that has no `response_format` attribute, and separately with a `tool_model` that has one
- **THEN** the planner agent's `output_schema` kwarg is `None` in the first case and `ClusterContext` in the second

#### Scenario: forecast agent is never constructed at __init__ time
- **WHEN** a `ReportAgent` is constructed with a `ForecastAgent` class replaced by a construction-counting fake
- **THEN** the construction counter is `0` immediately after `__init__` returns, and `self._forecast_agent` is `None`

### Requirement: _run_agent_with_retry retries on exception and times out without raising
`ReportAgent._run_agent_with_retry(agent, prompt, context)` SHALL call `agent.run(prompt)` in a background thread bounded by `self.LLM_TIMEOUT_SECONDS`, SHALL return the response's `.content` on success, SHALL retry (re-running `agent.run(prompt)`) up to `self.LLM_MAX_RETRIES` additional times after either an exception raised by `agent.run` or a timeout, and SHALL return `None` (never raise) once all attempts are exhausted, whether the final attempt raised or timed out.

#### Scenario: successful call returns content on the first attempt
- **WHEN** `agent.run(prompt)` returns a response whose `.content` is `"the content"`
- **THEN** `_run_agent_with_retry` returns `"the content"` and `agent.run` was called exactly once

#### Scenario: one failing attempt followed by a successful attempt succeeds
- **WHEN** `agent.run(prompt)` raises an exception on its first call and returns `"recovered"` on its second call
- **THEN** `_run_agent_with_retry` returns `"recovered"` and `agent.run` was called exactly twice

#### Scenario: every attempt raising exhausts retries and returns None
- **WHEN** `agent.run(prompt)` always raises an exception
- **THEN** `_run_agent_with_retry` returns `None` and `agent.run` was called exactly `self.LLM_MAX_RETRIES + 1` times

#### Scenario: every attempt exceeding the timeout also returns None
- **WHEN** `agent.run(prompt)` always takes longer than `self.LLM_TIMEOUT_SECONDS` to return
- **THEN** `_run_agent_with_retry` returns `None` after `self.LLM_MAX_RETRIES + 1` attempts, and the background thread from each timed-out attempt is left running rather than being cancelled or joined again

### Requirement: generate_report's incremental path normalizes citations, injects a programmatic bibliography, and sanitizes chart blocks
`ReportAgent.generate_report(signals, user_query)`, when `self.incremental_edit` is true, SHALL assemble a report beginning with a `# DeepEar` title and containing a `[TOC]` marker, SHALL replace every `[@KEY]`/`[[n]]` citation marker with a numbered anchor link and append a programmatic `## 参考文献` section built from `signals`' own source metadata (discarding any placeholder reference text the editor agent produced), SHALL repair a json-chart block whose closing fence is missing before chart processing consumes it, and SHALL return a `SimpleNamespace` whose `.content` is the assembled markdown and whose `.structured` is the result of `build_structured_report` on that markdown.

#### Scenario: two-signal, one-cluster report with a legacy citation marker and an unclosed chart block
- **WHEN** `generate_report` is called with two signals producing two bibliography keys, a planner response clustering both signals into one theme, a writer response containing both citation markers plus an unclosed `stock`-type json-chart block with an unparseable ticker, and canned incremental section-editor/summary/tail responses
- **THEN** the returned `.content` starts with `# DeepEar`, contains `[TOC]`, contains neither citation marker verbatim but does contain both markers' `(#ref-KEY)` anchors, does not contain the literal placeholder reference text the tail response supplied, contains no literal ` ```json-chart ` fence, contains the documented `<!-- 无法解析股票代码: ... -->` fallback comment, and the returned `.structured["clusters"]` has exactly one entry whose `signal_ids` is `[1, 2]`

### Requirement: _cluster_signals dispatches to the planner agent and falls back to an empty list on any failure to parse
`ReportAgent._cluster_signals(signals, user_query)` SHALL call `self.planner.run` exactly once with a task built from the signals' preview text, SHALL return the parsed `clusters` list when the planner's response content contains a JSON object with a `clusters` key, and SHALL return `[]` when the planner's response content is not parsable as such JSON or when calling `self.planner.run` raises any exception.

#### Scenario: valid cluster JSON from the planner is returned as-is
- **WHEN** `self.planner.run` returns content `{"clusters": [{"theme_title": "T", "signal_ids": [1, 2]}]}`
- **THEN** `_cluster_signals` returns `[{"theme_title": "T", "signal_ids": [1, 2]}]` and exactly one call was recorded against the planner

#### Scenario: unparsable planner response falls back to an empty list
- **WHEN** `self.planner.run` returns non-JSON content
- **THEN** `_cluster_signals` returns `[]`

#### Scenario: a planner exception falls back to an empty list
- **WHEN** `self.planner.run` raises an exception
- **THEN** `_cluster_signals` returns `[]` rather than propagating the exception

### Requirement: _build_forecast_map constructs the forecast agent lazily and at most once per call
`ReportAgent._build_forecast_map(report_text, signals)` SHALL return `{}` without calling `self._get_forecast_agent()` when `report_text` contains no forecast-type json-chart block, and SHALL, when it contains multiple distinct `(ticker, pred_len)` forecast requests each backed by a matching signal's `impact_tickers`, call `self._get_forecast_agent().generate_forecast(...)` once per distinct request while constructing the underlying `ForecastAgent` object at most once across all of those calls.

#### Scenario: no forecast request never constructs a ForecastAgent
- **WHEN** `_build_forecast_map` is called with report text containing no json-chart blocks
- **THEN** it returns `{}` and the `ForecastAgent` construction counter remains `0`

#### Scenario: two distinct forecast requests construct exactly one ForecastAgent
- **WHEN** `_build_forecast_map` is called with report text containing two forecast-type json-chart blocks for two different tickers, each backed by a signal whose `impact_tickers` names that ticker
- **THEN** the `ForecastAgent` construction counter is exactly `1`, and the constructed fake's `generate_forecast` was called exactly twice, once per ticker

### Requirement: _clean_markdown and _sanitize_json_chart_blocks handle fence edge cases without altering unrelated content
`ReportAgent._clean_markdown(text)` SHALL strip a leading `` ```markdown `` or bare `` ``` `` fence and a trailing `` ``` `` fence (and surrounding whitespace) from `text`, leaving already-fence-free text unchanged apart from stripping surrounding whitespace, and `ReportAgent._sanitize_json_chart_blocks(text)` SHALL leave `text` unchanged when it contains no `json-chart` marker or when every `json-chart` block already has a closing fence, and SHALL insert a closing fence immediately after the JSON object of a `json-chart` block whose closing fence is missing, leaving any content after that point unchanged.

#### Scenario: _clean_markdown strips markdown and bare fences
- **WHEN** `_clean_markdown` is called with `` "```markdown\n# Title\n\ncontent\n```" `` and separately with `` "```\nplain content\n```" ``
- **THEN** it returns `"# Title\n\ncontent"` and `"plain content"` respectively

#### Scenario: _sanitize_json_chart_blocks is a no-op without a json-chart marker or when already well-formed
- **WHEN** `_sanitize_json_chart_blocks` is called with plain markdown containing no `json-chart` marker, and separately with a `json-chart` block that already has its closing fence
- **THEN** both inputs are returned unchanged (aside from a well-formed block's fence-normalization pass, which does not alter its content)

#### Scenario: _sanitize_json_chart_blocks repairs a missing closing fence
- **WHEN** `_sanitize_json_chart_blocks` is called with a `json-chart` block whose JSON object is never followed by a closing fence, followed by unrelated trailing prose
- **THEN** the returned text has a closing fence inserted immediately after the JSON object, and the trailing prose is preserved unchanged after that fence

