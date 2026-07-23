## ADDED Requirements

### Requirement: Signal label normalization
`backtest.workflow.scoring._signal_label` SHALL return the analyst signal's `signal` attribute (defaulting to `"NEUTRAL"` when absent) as a stripped, uppercased string.

#### Scenario: Lowercase signal is normalized
- **WHEN** a signal object has `signal="bullish"`
- **THEN** `_signal_label(signal)` returns `"BULLISH"`

### Requirement: Priority score calculation is a pure function of analyst signals
`backtest.workflow.scoring._calculate_priority_score` SHALL compute a confidence-weighted average signal score adjusted by consistency, a bullish-consensus bonus, and a bearish-consensus penalty, using `_signal_label` (called directly, not via any instance) to classify each signal, and SHALL return `0.0` for an empty signal list.

#### Scenario: Empty signals score zero
- **WHEN** `_calculate_priority_score([])` is called
- **THEN** it returns `0.0`

#### Scenario: Strong bullish consensus scores above the unweighted average
- **WHEN** at least 70% of signals are `"BULLISH"`
- **THEN** the returned score includes a `+0.5` bonus over the confidence-weighted average

### Requirement: Signal consistency calculation is a pure function of analyst signals
`backtest.workflow.scoring._calculate_signal_consistency` SHALL return `1.0` for zero or one signals, and otherwise return `1.0` minus the coefficient of variation of the signals' mapped values (`BULLISH=1.0, NEUTRAL=0.5, BEARISH=0.0`), clamped so the result never goes below `0.0`.

#### Scenario: Single signal is fully consistent
- **WHEN** `_calculate_signal_consistency([signal])` is called with exactly one signal
- **THEN** it returns `1.0`

### Requirement: Signal summary aggregation
`backtest.workflow.scoring._aggregate_signal_from_summary` SHALL return `"BULLISH"` when a summary's `bullish_count` exceeds its `bearish_count`, `"BEARISH"` when the reverse holds, and `"NEUTRAL"` otherwise (including when both counts are equal).

#### Scenario: Tied counts return NEUTRAL
- **WHEN** a summary has equal `bullish_count` and `bearish_count`
- **THEN** `_aggregate_signal_from_summary(summary)` returns `"NEUTRAL"`

### Requirement: Smart priority ordering takes tickers as an explicit parameter
`backtest.workflow.scoring._get_smart_priority_order(signals, tickers)` SHALL return `list(tickers)` unchanged when `signals` is empty, and otherwise SHALL return tickers sorted descending by `(priority_score, bullish_count, signal_consistency, avg_confidence)`.

#### Scenario: Empty signals return the given tickers
- **WHEN** `_get_smart_priority_order({}, ["AAA", "BBB"])` is called
- **THEN** it returns `["AAA", "BBB"]`

#### Scenario: Higher priority score sorts first
- **WHEN** ticker A has a higher `priority_score` than ticker B in `signals`
- **THEN** A appears before B in the returned order

### Requirement: workflow_adapter delegators preserve monkeypatch and call surfaces
`BacktestWorkflowAdapter` SHALL expose `_signal_label`, `_aggregate_signal_from_summary`, `_calculate_priority_score`, `_calculate_signal_consistency`, and `_get_smart_priority_order` as same-named class attributes that delegate to `backtest.workflow.scoring`'s module functions, with `_get_smart_priority_order` supplying `self.tickers` as the `tickers` argument, so `adapter.<name>(...)` calls and instance-attribute monkeypatches (`monkeypatch.setattr(adapter, "_get_smart_priority_order", ...)`) keep working unchanged.

#### Scenario: Adapter delegate produces the same result as the module function
- **WHEN** `adapter._calculate_priority_score(signals)` is called on any `BacktestWorkflowAdapter` instance
- **THEN** it returns the same value as `backtest.workflow.scoring._calculate_priority_score(signals)`

#### Scenario: Instance-level monkeypatch of the delegator still short-circuits
- **WHEN** a test does `monkeypatch.setattr(adapter, "_get_smart_priority_order", lambda signals: ["AAA", "BBB"])`
- **THEN** subsequent calls to `adapter._get_smart_priority_order(...)` on that instance return `["AAA", "BBB"]` without invoking `backtest.workflow.scoring._get_smart_priority_order`
