## Context

Day-shared multi-personality backtests already collect `daily_decisions` in memory and write per-personality `trades.csv` plus `broker_audit.jsonl`. Analyst outputs are cached under `data/backtest/shared_analyst_cache/<run_id>`, but the comparison report bundle does not contain a single durable decision timeline. Company-news provider logs currently expose only `items=<count>`, so a zero count cannot be diagnosed without rerunning or instrumenting the provider.

## Goals / Non-Goals

**Goals:**
- Export all per-date, per-personality, per-ticker decisions from day-shared multi-personality runs.
- Export company-news fetch/filter diagnostics so zero-item news results are explainable after a run.
- Extend artifact review to validate the new artifacts when they are expected.

**Non-Goals:**
- Persist full raw news article payloads in reports.
- Change trading behavior, provider selection, or news sentiment logic.
- Add a UI for inspecting diagnostics.

## Decisions

- Write `daily_decisions.jsonl` from `MultiPersonalityBacktestEngine.comparison.daily_decisions` during comparison report generation. JSONL keeps the artifact stream-friendly and consistent with broker audit output.
- Normalize decisions before writing so dataclasses, numpy/pandas scalar types, and private execution metadata become JSON-safe fields.
- Record news diagnostics through an in-process collector module. The FMP provider can append count-only records as it filters rows; the multi-personality report generator can export and clear the records for the run.
- Keep diagnostic records count-only. Endpoint names, provider, ticker, trading date, raw count, filter counts, final count, and stage metadata are enough to explain why a final result was zero without copying article text.

## Risks / Trade-offs

- In-process diagnostics can include records from concurrent backtests in the same Python process → include run export timing and provider/date/ticker metadata; clear after export to reduce cross-run bleed.
- JSONL artifacts add small report files → use compact normalized records and avoid raw news payloads.
- Existing comparison results will not have these artifacts → artifact review should require them only for new report bundles that contain day-shared execution metadata or when explicitly invoked on generated runs.
