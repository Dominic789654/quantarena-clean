## Why

Multi-personality backtest reports currently preserve trades, broker audit events, metrics, and analyst cache files, but the final report bundle does not expose every per-day personality decision in one machine-readable artifact. Company-news runs can also show `items=0` without explaining whether the raw provider returned no rows, date filtering removed rows, or ticker matching removed rows.

## What Changes

- Add a multi-personality `daily_decisions.jsonl` report artifact that records each date/personality/ticker decision, including HOLD decisions and source justifications.
- Add a company-news diagnostics artifact that records raw row counts and filtering counts per date/ticker/provider without storing full raw provider payloads.
- Include the new artifacts in comparison report generation and artifact review so missing decision artifacts or unexplained news diagnostics are caught after runs.
- No breaking changes.

## Capabilities

### New Capabilities
- `backtest-news-diagnostics`: Records provider-level company-news collection diagnostics for backtest runs.

### Modified Capabilities
- `multi-personality-shared-phase-execution`: Multi-personality report bundles include daily personality decision artifacts.

## Impact

- Affected code: `backtest/multi_personality_engine.py`, `deepfund/src/apis/fmp/api.py`, `deepfund/src/apis/router.py`, artifact review utilities, and focused tests.
- Affected artifacts: `reports/multi_personality/<run_id>/daily_decisions.jsonl` and `news_diagnostics.jsonl`.
- No new runtime dependencies.
