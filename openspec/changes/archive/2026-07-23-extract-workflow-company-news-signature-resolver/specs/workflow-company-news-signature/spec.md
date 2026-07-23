## ADDED Requirements

### Requirement: Stable JSON signature is deterministic
`backtest.workflow.company_news_signature._stable_json_signature(payload)` SHALL return a 12-character lowercase hex digest that is identical for two calls with structurally equal payloads regardless of key order, and different for payloads that differ in content.

#### Scenario: Key order does not affect the signature
- **WHEN** `_stable_json_signature({"a": 1, "b": 2})` and `_stable_json_signature({"b": 2, "a": 1})` are both called
- **THEN** both calls return the same 12-character digest

#### Scenario: Different content produces a different signature
- **WHEN** `_stable_json_signature({"a": 1})` and `_stable_json_signature({"a": 2})` are both called
- **THEN** the two returned digests differ

### Requirement: News item normalization extracts a stable field subset
`backtest.workflow.company_news_signature._normalize_news_item(news_item)` SHALL return a dict with exactly the keys `title`, `publish_time`, `publisher`, `link`, and `summary`, populated from a pydantic-model-like object (via `model_dump()`), a plain dict, or a duck-typed object (via `getattr`), in that preference order.

#### Scenario: Dict input is normalized to the fixed key set
- **WHEN** `_normalize_news_item({"title": "t", "extra": "ignored"})` is called
- **THEN** the returned dict has exactly the keys `title`, `publish_time`, `publisher`, `link`, `summary`, with `title == "t"` and the other fields `None`

### Requirement: Company-news signature payload resolution reads adapter market/api_source state
`backtest.workflow.company_news_signature._get_company_news_signature_payload(adapter, trading_date, ticker)` SHALL fetch news for `ticker` on `trading_date` via `apis.router.Router` resolved from `adapter.market` and `adapter.api_source`, and SHALL return a payload dict containing `ticker`, `trading_date`, `count`, `items` (normalized via `adapter._normalize_news_item`), `prompt_data`, and `signature` (via `adapter._stable_json_signature(prompt_data)`).

#### Scenario: Payload signature changes when the underlying news changes
- **WHEN** `_get_company_news_signature_payload` is called twice for the same ticker/date but the router returns different news items the second time
- **THEN** the two returned payloads' `signature` values differ

### Requirement: Prefetched analyst payload lookup is a pure dict lookup
`backtest.workflow.company_news_signature._get_prefetched_analyst_payload(prefetched_analyst_data, analyst_key)` SHALL return `prefetched_analyst_data[analyst_key]` if `prefetched_analyst_data` is a dict and that value is itself a dict, and SHALL return `None` in every other case (including `prefetched_analyst_data` not being a dict, or the key missing, or the value not being a dict).

#### Scenario: Non-dict input returns None
- **WHEN** `_get_prefetched_analyst_payload(None, "company_news")` is called
- **THEN** it returns `None`

### Requirement: Ensuring the company-news prefetched payload reuses or resolves via the adapter delegator
`backtest.workflow.company_news_signature._ensure_company_news_prefetched_payload(adapter, trading_date, ticker, prefetched_analyst_data=None)` SHALL return the existing `"company_news"` entry from `prefetched_analyst_data` if present and a dict, and otherwise SHALL resolve it by calling `adapter._get_company_news_signature_payload(trading_date, ticker)` (the delegator, not the bare module function) and, if `prefetched_analyst_data` is a dict, store the resolved payload back into it under `"company_news"`.

#### Scenario: A monkeypatched adapter delegator is honored
- **WHEN** `BacktestWorkflowAdapter._get_company_news_signature_payload` is monkeypatched as a class attribute and `_ensure_company_news_prefetched_payload(adapter, trading_date, ticker)` is called with no cached payload present
- **THEN** the resolved payload comes from the monkeypatched function, not the original

### Requirement: Phase1 prefetched analyst inputs only fetch company_news when it is an active analyst
`backtest.workflow.company_news_signature._build_phase1_prefetched_analyst_inputs(adapter, trading_date, prices)` SHALL return an empty dict if `"company_news"` is not in `adapter.analysts`, and otherwise SHALL return a dict keyed by every ticker in `sorted(prices)`, each mapping to `{"company_news": <payload from adapter._get_company_news_signature_payload(trading_date, ticker)>}`.

#### Scenario: company_news not in analysts short-circuits
- **WHEN** `adapter.analysts` does not contain `"company_news"`
- **THEN** `_build_phase1_prefetched_analyst_inputs(adapter, trading_date, prices)` returns `{}` without calling the router

### Requirement: Analyst input signature resolution is company_news-specific
`backtest.workflow.company_news_signature._resolve_analyst_input_signature(adapter, trading_date, ticker, analyst_key, prefetched_analyst_data=None)` SHALL return the `"company_news"` payload's `signature` (as a string, via `adapter._ensure_company_news_prefetched_payload`) when `analyst_key == "company_news"`, and SHALL return `None` for every other `analyst_key`.

#### Scenario: Non-company_news analyst key returns None
- **WHEN** `_resolve_analyst_input_signature(adapter, trading_date, ticker, "fundamental")` is called
- **THEN** it returns `None`

### Requirement: Phase1 input metadata aggregates a stable signature across prices, tickers, and (when active) company_news
`backtest.workflow.company_news_signature._resolve_phase1_input_metadata(adapter, trading_date, prices, prefetched_analyst_inputs=None)` SHALL return metadata containing `price_input_signature`, `tickers_input_signature`, and `phase1_input_signature`, and, when `"company_news"` is in `adapter.analysts`, additionally `news_input_signature` and `news_input_signatures_by_ticker` (one entry per ticker in `prices`, resolved via `adapter._ensure_company_news_prefetched_payload`); `phase1_input_signature` SHALL change whenever any component signature (`prices`, `tickers`, or `company_news` when active) changes.

#### Scenario: News signature change propagates to phase1_input_signature
- **WHEN** `_resolve_phase1_input_metadata` is called twice with the same `prices` but the company-news payload's signature differs between calls
- **THEN** the two calls' `news_input_signature` and `phase1_input_signature` values both differ

### Requirement: workflow_adapter delegators keep every existing call site and monkeypatch working
`BacktestWorkflowAdapter` SHALL expose `_stable_json_signature`, `_normalize_news_item`, `_get_company_news_signature_payload`, `_get_prefetched_analyst_payload`, `_ensure_company_news_prefetched_payload`, `_build_phase1_prefetched_analyst_inputs`, `_resolve_analyst_input_signature`, and `_resolve_phase1_input_metadata` as same-named class attributes (static or instance methods) that delegate to `backtest.workflow.company_news_signature`'s module functions, and every internal call between these eight (both within the module and from `BacktestWorkflowAdapter`'s other methods, e.g. `_process_single_ticker_for_signals_v2`) SHALL go through the instance delegator (`self.<name>(...)`), never a direct module-level call, so that monkeypatching any of the eight as a class attribute on `BacktestWorkflowAdapter` is honored by every caller.

#### Scenario: Class-attribute monkeypatch of _get_company_news_signature_payload propagates through the full resolver chain
- **WHEN** `_get_company_news_signature_payload` is monkeypatched as a class attribute on `BacktestWorkflowAdapter`, and `load_or_compute_shared_phase1` is called on an adapter configured with `company_news` in `analysts`
- **THEN** the monkeypatched payload (not the real router-backed one) is reflected in the resulting `SharedPhase1Artifact`'s `enhanced_signals` and `metadata`
