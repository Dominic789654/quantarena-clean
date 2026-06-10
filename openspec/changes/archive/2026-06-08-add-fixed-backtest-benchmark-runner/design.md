## Context

The fixed benchmark has already been used manually with these parameters:
AAPL/MSFT/NVDA, US market, 2026-06-01 through 2026-06-05, 10000 initial cash,
simple mode and DeepSeek technical LLM mode. The repository now has reusable
report artifacts and a static HTML visualizer, so the remaining gap is a stable
runner that invokes the existing backtest path and records comparable outputs.

## Goals / Non-Goals

**Goals:**
- Provide a small committed runner for `simple`, `llm`, and `both`.
- Keep the benchmark configuration explicit and inspectable in code.
- Generate dashboards through the existing visualizer instead of duplicating
  report rendering.
- Produce a summary JSON that CI, reviews, or future dashboards can consume.

**Non-Goals:**
- Do not add a scheduler, CI job, or live market data snapshot system.
- Do not change the backtest engine, strategy logic, risk gate, or visualizer
  behavior.
- Do not embed API keys or bypass existing provider/LLM environment validation.
- Do not make this a general experiment framework; it is one fixed benchmark.

## Decisions

- Add a `quantarena.fixed_backtest_benchmark` module plus a
  `scripts/run_fixed_backtest_week.py` wrapper.
  - Rationale: the module is unit-testable and importable, while the script is
    the direct workflow command users asked for.

- Invoke `run.py` as a subprocess rather than importing backtest internals.
  - Rationale: the benchmark should exercise the same CLI path used by manual
    runs, including environment validation and report generation.

- Discover the report directory from the subprocess output first, then fall back
  to known `reports/backtest/<run_id>` conventions.
  - Rationale: this preserves compatibility with current output while avoiding
    tight coupling to one log line.

- Write `summary.json` to a benchmark output directory, defaulting under
  `reports/backtest/fixed_benchmarks/`.
  - Rationale: the summary is a benchmark-level artifact, separate from each
    mode's generated backtest report directory.

## Risks / Trade-offs

- [Risk] The fixed dates depend on provider data availability and credentials.
  -> Mitigation: keep the existing `run.py` validation path and record failures
  in the summary.

- [Risk] LLM output is nondeterministic even with fixed market data.
  -> Mitigation: record run ids, mode, command arguments, and metrics so changes
  remain auditable.

- [Risk] Parsing subprocess output can break if `run.py` output changes.
  -> Mitigation: support both explicit report path parsing and run-id fallback.
