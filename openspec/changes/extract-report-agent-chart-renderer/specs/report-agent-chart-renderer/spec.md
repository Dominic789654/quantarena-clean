## ADDED Requirements

### Requirement: process_charts dispatches json-chart blocks by type through required keyword-only threaded dependencies, with no chart blocks passing content through unchanged
`deepear.src.agents.report.chart_renderer.process_charts(content, signals=None, forecast_map=None, *, db, tool_model, get_forecast_agent, agent_cls)` SHALL require `db`, `tool_model`, `get_forecast_agent`, and `agent_cls` as keyword-only arguments with no defaults, SHALL return `content` unchanged (aside from the separate invalid-forecast-ticker HTML-comment substitution) when it contains no ` ```json-chart ` fenced blocks, SHALL dispatch each matched block on its parsed JSON `"type"` field to the `stock`/`forecast`/`sentiment`/`isq`/`transmission` handling described by the other requirements in this capability, SHALL return the block re-fenced as a plain ` ```json ` block when its type is unrecognized or its handling falls through without returning, and SHALL catch any exception raised anywhere while handling a single block and return that block's original, unrendered text in its place rather than raising or dropping content.

#### Scenario: Content with no chart blocks is returned unchanged
- **WHEN** `process_charts("# Report\n\nplain markdown, no chart blocks.\n", db=..., tool_model=..., get_forecast_agent=..., agent_cls=...)` is called
- **THEN** the returned string equals the input string exactly

#### Scenario: An unrecognized chart type falls back to raw JSON display
- **WHEN** `process_charts` is called on a block with `"type": "widget"`
- **THEN** the block is replaced with the same JSON re-fenced as \`\`\`json ... \`\`\` (not \`\`\`json-chart)

#### Scenario: An exception during a block's handling falls back to the original block text
- **WHEN** the underlying chart-drawing call for a block raises an exception
- **THEN** `process_charts`'s output contains that block's original, unrendered ` ```json-chart ... ``` ` text unchanged, and no exception propagates out of `process_charts`

### Requirement: The stock chart type resolves one or more tickers (direct digit match or fuzzy search) and renders one chart per resolved ticker, optionally overlaying a forecast via get_forecast_agent
For a block with `"type": "stock"`, `process_charts` SHALL split the block's `ticker` field on commas/whitespace into candidate tokens, SHALL accept a token directly if its dot-suffix-stripped form is all-digit with length 5 or 6, SHALL otherwise attempt a fuzzy `stock_tools.search_ticker` lookup (constructed internally as `StockTools(db, auto_update=False)`) for tokens longer than one character or short digit tokens, SHALL emit an unparseable-ticker HTML comment and skip rendering when zero tokens resolve, SHALL, for each resolved ticker, fetch a 90-day price history and skip rendering (logging a warning) when that history is empty, SHALL, only when the block's `show_forecast` or `forecast` field is truthy, call `get_forecast_agent().generate_forecast(ticker, related_signals)` (swallowing any exception into a `None` forecast) and pass the result into the chart as an overlay, SHALL render one iframe per ticker with non-empty history and a chart, and SHALL emit a no-data HTML comment when every resolved ticker's history was empty.

#### Scenario: A valid 6-digit ticker with non-empty history renders one iframe
- **WHEN** `process_charts` is called on a `{"type": "stock", "ticker": "600001", "title": "600001 Trend"}` block with a `stock_tools`-collaborator DataFrame that is non-empty for `"600001"`
- **THEN** the output contains an iframe referencing `charts/stock_600001_...` and the caption text `交互式图表: 600001 Trend`

#### Scenario: A ticker with no available price history emits an HTML comment
- **WHEN** `process_charts` is called on a `{"type": "stock", "ticker": "600002"}` block whose `stock_tools` collaborator returns an empty DataFrame for `"600002"`
- **THEN** the output contains `<!-- 无法获取股票数据: 600002 -->` and no iframe

#### Scenario: A ticker string with no digits and no fuzzy match emits an unparseable-ticker HTML comment
- **WHEN** `process_charts` is called on a `{"type": "stock", "ticker": "?!?"}` block
- **THEN** the output contains `<!-- 无法解析股票代码: ?!? -->`

### Requirement: The forecast chart type prefers a pre-computed forecast_map entry over calling get_forecast_agent, and caches each unique (ticker, pred_len) once per process_charts call
For a block with `"type": "forecast"`, `process_charts` SHALL emit an unsupported-ticker warning paragraph and skip rendering when the block's cleaned ticker is not all-digit with length 5 or 6, SHALL, for a resolved `(ticker, pred_len)` key already present in the per-call `rendered_forecast_html` cache, return that cached HTML without any further work, SHALL, when `forecast_map` is provided and contains the key, use that entry's forecast without calling `get_forecast_agent`, SHALL, otherwise, call `get_forecast_agent().generate_forecast(ticker, related_signals, pred_len=pred_len)` exactly once for that key, SHALL emit a no-data HTML comment (caching it under the key) when the ticker's price history is empty, SHALL render an iframe plus a rationale paragraph (from the forecast's `rationale` field) when a forecast object is available, and SHALL fall back to a history-only chart (or an all-failed HTML comment if even that has no chart) when no forecast object is available, caching whichever HTML it returns under the key.

#### Scenario: A forecast_map hit never calls get_forecast_agent
- **WHEN** `process_charts` is called with `forecast_map={("600001", 5): <ForecastResult>}` on a matching `{"type": "forecast", "ticker": "600001", "pred_len": 5}` block
- **THEN** the injected `get_forecast_agent` callable is never invoked, and the output contains the forecast's rationale text

#### Scenario: A forecast_map miss calls get_forecast_agent exactly once for that key
- **WHEN** `process_charts` is called with no matching `forecast_map` entry on a `{"type": "forecast", "ticker": "600001", "pred_len": 5}` block
- **THEN** the injected `get_forecast_agent` callable is invoked, and its returned forecast's rationale text appears in the output

#### Scenario: Duplicate forecast blocks for the same key render via the per-call cache without a second generate_forecast call
- **WHEN** `process_charts` is called on content containing the identical `{"type": "forecast", "ticker": "600001", "pred_len": 5}` block twice
- **THEN** both occurrences are replaced with identical rendered HTML, and the underlying forecast agent's `generate_forecast` is called exactly once for that key

### Requirement: The sentiment chart type queries daily_news via the injected db collaborator with a parameterized keyword query and a keyword-broadening fallback
For a block with `"type": "sentiment"` and a non-empty `keywords` list, `process_charts` SHALL build and execute (via `db.execute_query`) a parameterized `SELECT publish_time, sentiment_score FROM daily_news WHERE (...) AND sentiment_score IS NOT NULL ORDER BY publish_time` query with one `content LIKE ?` condition per keyword, SHALL, when that query returns no rows, retry with a second query built from the keywords further split on whitespace and deduplicated (dropping single-character tokens), SHALL, when rows are available (from either query), aggregate scores by day and render a sentiment trend chart as an iframe, and SHALL render a "no data" placeholder paragraph (naming the block's title) when both queries return no rows.

#### Scenario: A keyword query with results renders a sentiment trend iframe
- **WHEN** `process_charts` is called on a `{"type": "sentiment", "keywords": ["宁德时代"], "title": "Mood"}` block whose `db.execute_query` returns non-empty sentiment rows for the first query
- **THEN** `db.execute_query` is called with a query string containing `sentiment_score` and params `("%宁德时代%",)`, and the output contains an iframe referencing `charts/sentiment_...` and the caption `交互式图表: Mood`

#### Scenario: Empty results from both the initial and broadened queries render a placeholder
- **WHEN** `process_charts` is called on the same block but `db.execute_query` returns no rows for either query
- **THEN** the output contains a placeholder paragraph mentioning `暂无足够历史数据生成` and the block's title, and `db.execute_query` was called twice

### Requirement: The transmission chart type constructs a throwaway agent via the injected agent_cls factory to generate Draw.io XML, retrying up to twice before falling back to a Pyecharts graph
For a block with `"type": "transmission"` and a non-empty `nodes` list, `process_charts` SHALL, up to 2 attempts, construct `agent_cls(model=tool_model, instructions=[<drawio system prompt>], markdown=False)` and call its `.run(...)` with a Draw.io-XML-generation task prompt built from `nodes` and the block's title, SHALL, when the response content contains a `<mxGraphModel>...</mxGraphModel>` span, extract it and render it to an iframe, marking the attempt successful, SHALL, when no attempt within the retry budget succeeds (extraction fails, rendering fails, or an exception is raised), fall back to rendering a Pyecharts transmission graph as an iframe instead, and SHALL sleep 1 second between a failed attempt and the next one (but not after the final attempt).

#### Scenario: A successful Draw.io XML response renders an AI-generated iframe
- **WHEN** the injected `agent_cls`'s `.run(...)` returns content containing a valid `<mxGraphModel>...</mxGraphModel>` span for a `{"type": "transmission", "nodes": [...], "title": "Logic Chain"}` block
- **THEN** the output contains an iframe referencing `charts/trans_...` and the caption `交互式逻辑推演图: Logic Chain (AI Generated)`

#### Scenario: A response with no extractable XML across all attempts falls back to a Pyecharts graph
- **WHEN** the injected `agent_cls`'s `.run(...)` never returns a response containing `<mxGraphModel>...</mxGraphModel>` across both attempts
- **THEN** the output contains an iframe referencing `charts/trans_legacy_...` and the caption `逻辑传导拓扑图: Logic Chain`

### Requirement: ReportAgent keeps a real bound-method delegator for _process_charts that forwards all four threaded dependencies, resolving agent_cls from its own module-global Agent at call time
`ReportAgent._process_charts(self, content, signals=None, forecast_map=None)` SHALL remain a real bound instance method returning `deepear.src.agents.report.chart_renderer.process_charts(content, signals, forecast_map, db=self.db, tool_model=self.tool_model, get_forecast_agent=self._get_forecast_agent, agent_cls=Agent)`'s result unchanged, where `Agent` is read as `report_agent.py`'s own module-global name fresh at the time each call executes, such that the method remains patchable as a class or instance attribute, the one internal `self._process_charts(...)` call site inside `generate_report` is intercepted by any such patch, and any monkeypatch of `report_agent_module.Agent` -- whether applied before or after a `ReportAgent` instance is constructed -- is honored by the next `_process_charts` call's nested throwaway Agent construction.

#### Scenario: The delegator's output matches the module function's output for identical inputs
- **WHEN** `ReportAgent._process_charts(content)` and `chart_renderer.process_charts(content, None, None, db=..., tool_model=..., get_forecast_agent=..., agent_cls=...)` are called with the same underlying `db`/`tool_model`/`get_forecast_agent`/`agent_cls` values
- **THEN** both calls return byte-identical output

#### Scenario: Re-patching report_agent's module-global Agent after construction still affects the next call
- **WHEN** a `ReportAgent` instance is constructed with one patched `Agent`, `report_agent_module.Agent` is then re-patched to a second fake class, and `_process_charts` is called on content containing a `"transmission"`-type block
- **THEN** the nested throwaway Agent construction for that call is made using the second fake class, not the first
