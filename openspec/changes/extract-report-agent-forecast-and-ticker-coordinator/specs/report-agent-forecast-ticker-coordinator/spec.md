## ADDED Requirements

### Requirement: clean_ticker normalizes a raw ticker string down to its digit code
`deepear.src.agents.report.ticker_utils.clean_ticker(ticker_raw)` SHALL strip leading/trailing whitespace from `ticker_raw` (treating `None` as an empty string), SHALL return `""` if the stripped value is empty, SHALL otherwise take only the text before the first `","` if a comma is present and only the text before the first `"."` if a dot is present (comma split applied before dot split), SHALL then extract every digit character from the remaining text, and SHALL return that digit string if non-empty, otherwise the remaining (non-digit) text unchanged.

#### Scenario: A comma-separated multi-ticker string keeps only the first entry's digits
- **WHEN** `clean_ticker("600001,000002")` is called
- **THEN** it returns `"600001"`

#### Scenario: A dotted exchange-suffixed ticker keeps only the digits before the dot
- **WHEN** `clean_ticker("002371.SZ")` is called
- **THEN** it returns `"002371"`

#### Scenario: A purely non-numeric string with no digits is returned unchanged
- **WHEN** `clean_ticker("ABC")` is called
- **THEN** it returns `"ABC"`

#### Scenario: Empty or whitespace-only input returns an empty string
- **WHEN** `clean_ticker("")`, `clean_ticker("   ")`, and `clean_ticker(None)` are each called
- **THEN** each call returns `""`

### Requirement: signal_mentions_ticker matches a signal to a cleaned ticker via structured data first, then text fallback
`deepear.src.agents.report.ticker_utils.signal_mentions_ticker(signal, ticker_digits)` SHALL return `False` immediately if `ticker_digits` is falsy, SHALL otherwise read `signal`'s `impact_tickers` (via attribute access for non-dict `signal`, via `.get` for dict `signal`) and, if it is a list, SHALL return `True` as soon as any dict item's `ticker`/`code`/`symbol` field, cleaned via `clean_ticker`, equals `ticker_digits`, SHALL otherwise fall back to checking whether `ticker_digits` appears as a substring of `signal`'s combined `title`/`summary`/`analysis` text (attribute or dict access, each defaulting to `""`), and SHALL return `False` (swallowing the exception) if any lookup on `signal` raises.

#### Scenario: A structured impact_tickers entry matches regardless of exchange-suffix noise
- **WHEN** `signal_mentions_ticker({"impact_tickers": [{"ticker": "600001.SH"}]}, "600001")` is called
- **THEN** it returns `True`

#### Scenario: No structured match falls back to a text substring match
- **WHEN** `signal_mentions_ticker({"title": "600001 rallies", "summary": "", "analysis": ""}, "600001")` is called
- **THEN** it returns `True`

#### Scenario: Neither structured data nor text mentions the ticker
- **WHEN** `signal_mentions_ticker({"title": "unrelated", "summary": "", "analysis": ""}, "600001")` is called
- **THEN** it returns `False`

#### Scenario: An empty ticker_digits short-circuits to False without inspecting signal
- **WHEN** `signal_mentions_ticker(object(), "")` is called
- **THEN** it returns `False`

#### Scenario: Attribute-style signals are matched the same way as dict signals
- **WHEN** `signal_mentions_ticker(<object with impact_tickers=[{"ticker": "600001"}]>, "600001")` and `signal_mentions_ticker({"impact_tickers": [{"ticker": "600001"}]}, "600001")` are both called
- **THEN** both calls return `True`

### Requirement: extract_forecast_requests parses forecast json-chart blocks out of report markdown
`deepear.src.agents.report.forecast_requests.extract_forecast_requests(text, context_window_chars=1200)` SHALL return `[]` when `text` is falsy, SHALL otherwise scan every ` ```json-chart ... ``` ` fenced block for a JSON object with `"type": "forecast"`, SHALL skip any block that fails to parse as JSON or whose `type` is not `"forecast"`, SHALL derive each request's `ticker` via `clean_ticker` on the block's `ticker` field and skip the block if the cleaned value is not all-digit with length 5 or 6, SHALL clamp `pred_len` (default `5` on missing/unparseable input) to the inclusive range `[1, 20]`, SHALL build `title` from the block's `title` field or default to `f"{ticker_raw} 预测"`, SHALL prefer a structured context built from the block's `selected_scenario`/`selection_reason`/`scenarios` fields over the raw surrounding-text snippet (captured within `context_window_chars` characters on each side of the block, with the matched block and any other `json-chart` blocks stripped out) whenever any structured field is present, and SHALL truncate the resulting `context_snippet` to 3500 characters (appending a truncation notice) if longer.

#### Scenario: A well-formed forecast block yields one request with the expected shape
- **WHEN** `extract_forecast_requests('```json-chart\n{"type": "forecast", "ticker": "600001", "pred_len": 5, "title": "T1"}\n```\n')` is called
- **THEN** it returns a single-element list whose entry has `ticker == "600001"`, `pred_len == 5`, `title == "T1"`, and a `context_snippet` key

#### Scenario: A ticker that is not 5 or 6 digits after cleaning is rejected
- **WHEN** `extract_forecast_requests` is called on a block with `"ticker": "12"` (or any non-digit ticker with no embedded digits)
- **THEN** the returned list contains no entry for that block

#### Scenario: A structured scenario/selection_reason takes priority over the raw snippet
- **WHEN** `extract_forecast_requests` is called on a block that sets `selected_scenario` and `selection_reason` alongside surrounding prose
- **THEN** the entry's `context_snippet` contains the rendered `"最可能情景"`/`"归因"` lines and not the raw surrounding prose

#### Scenario: No text or no matching blocks yields an empty list
- **WHEN** `extract_forecast_requests("")`, `extract_forecast_requests(None)`, and `extract_forecast_requests("plain text, no chart blocks")` are each called
- **THEN** each call returns `[]`

### Requirement: build_forecast_map generates each unique forecast once via an injected lazy forecast-agent callable
`deepear.src.agents.report.forecast_requests.build_forecast_map(report_text, signals=None, *, get_forecast_agent)` SHALL require `get_forecast_agent` as a keyword-only argument (no default) standing in for the original method's `self._get_forecast_agent`, SHALL return `{}` without calling `get_forecast_agent` at all when `extract_forecast_requests(report_text)` yields no requests, SHALL otherwise group requests by `(ticker, pred_len)` merging titles/context snippets per group, SHALL, when `signals` is provided and yields at least one structured `impact_tickers`-derived ticker, restrict generation to only tickers in that allowlist (skipping any group's ticker not in it), SHALL, when `signals` is provided and non-empty, additionally require at least one signal matched via `signal_mentions_ticker` for a group's ticker before generating (skipping the group otherwise), and SHALL, for each remaining group, call `get_forecast_agent().generate_forecast(ticker, related_signals, pred_len=pred_len, extra_context=...)` exactly once, catching and logging (not raising) any exception from that call and omitting the group's entry from the returned map on failure.

#### Scenario: No forecast requests means the injected callable is never invoked
- **WHEN** `build_forecast_map("no chart blocks here", signals=[...], get_forecast_agent=counting_callable)` is called
- **THEN** it returns `{}` and `counting_callable` was never called

#### Scenario: Two distinct forecast requests each generate once, sharing one underlying agent construction
- **WHEN** `build_forecast_map(text_with_two_distinct_forecast_blocks, signals=matching_signals, get_forecast_agent=counting_callable)` is called, where `counting_callable` returns the same cached fake agent object on every call while incrementing a construction counter only the first time
- **THEN** the returned map has two entries, `counting_callable`'s underlying construction counter equals `1`, and the fake agent's `generate_forecast` was called once per distinct `(ticker, pred_len)` group

#### Scenario: Duplicate forecast blocks for the same (ticker, pred_len) generate only once
- **WHEN** `build_forecast_map` is called on text containing the same `(ticker, pred_len)` forecast block twice
- **THEN** the returned map has exactly one entry for that key and `generate_forecast` was called exactly once for it

#### Scenario: A signal-backed allowlist skips ungrounded tickers
- **WHEN** `build_forecast_map` is called with `signals` whose structured `impact_tickers` name only one of two requested tickers
- **THEN** the returned map omits the ungrounded ticker's entry and `generate_forecast` is not called for it

### Requirement: ReportAgent keeps real delegators of matching binding kind for all four moved names, and leaves _get_forecast_agent untouched
`ReportAgent._clean_ticker` SHALL remain a real `@staticmethod` returning `deepear.src.agents.report.ticker_utils.clean_ticker`'s result unchanged, `ReportAgent._signal_mentions_ticker` SHALL remain a real `@classmethod` returning `deepear.src.agents.report.ticker_utils.signal_mentions_ticker`'s result unchanged, `ReportAgent._extract_forecast_requests(self, text, context_window_chars=1200)` SHALL remain a real bound instance method returning `deepear.src.agents.report.forecast_requests.extract_forecast_requests(text, context_window_chars)`'s result unchanged, `ReportAgent._build_forecast_map(self, report_text, signals=None)` SHALL remain a real bound instance method returning `deepear.src.agents.report.forecast_requests.build_forecast_map(report_text, signals, get_forecast_agent=self._get_forecast_agent)`'s result unchanged, and `ReportAgent._get_forecast_agent` SHALL remain exactly as it was before this change (a bound instance method lazily constructing and caching `self._forecast_agent`), such that every one of the four moved names remains patchable as a class attribute or instance attribute, every internal call site inside `_extract_forecast_requests`/`_build_forecast_map`/`generate_report` is intercepted by such a patch, and the lazy-cache's "construct at most once per instance" property is preserved end to end.

#### Scenario: Each delegator produces output identical to its module function
- **WHEN** each of the four `ReportAgent` attributes is called with the same arguments as the corresponding module function (using a real `ReportAgent` instance's own `self._get_forecast_agent` for `_build_forecast_map`)
- **THEN** each pair returns byte-identical/deep-equal results

#### Scenario: Class-level static and classmethod calls keep working without an instance
- **WHEN** `ReportAgent._clean_ticker(ticker_raw)` and `ReportAgent._signal_mentions_ticker(signal, ticker_digits)` are called directly on the class, with no `ReportAgent` instance constructed
- **THEN** each returns the same value the corresponding module function would return

#### Scenario: The lazy forecast-agent cache still constructs at most once across a real ReportAgent's forecast requests
- **WHEN** a real `ReportAgent` instance's `_build_forecast_map(report_text, signals=...)` is called with report text containing multiple distinct forecast requests
- **THEN** the underlying (would-be Kronos-backed) forecast-agent class is constructed at most once, exactly as before this change
