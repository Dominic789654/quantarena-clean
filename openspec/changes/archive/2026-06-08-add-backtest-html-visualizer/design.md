## Context

Generated backtest output already contains the data needed for a browser dashboard: `metrics.json`, `equity_curve.csv`, and `trades.csv`. The current reporting layer generates Markdown, CSV, JSON, and PNG files, but there is no offline interactive page for switching between all-stock and single-stock views.

## Goals / Non-Goals

**Goals:**
- Generate a standalone HTML file from one existing backtest report artifact directory.
- Reuse the pure `quantarena.report_artifacts` loader so visualization is read-only and does not execute backtests.
- Embed run metrics, equity curve, trades, and final positions as JSON for offline browser use.
- Provide ticker controls for all-stock and single-stock inspection of trades and positions.
- Expose the generator through the stable `quantarena` CLI.

**Non-Goals:**
- Run backtests, fetch market data, call LLM APIs, or mutate existing report artifacts.
- Add a web server or external JavaScript/CSS dependencies.
- Compare multiple report runs in one page; this change targets one report directory at a time.
- Rebuild PNG charts; the visualizer renders lightweight SVG charts in the browser.

## Decisions

- Build a standalone static HTML renderer under `quantarena.backtest_visualizer`.
  - Rationale: visualization is an artifact inspection tool, not part of the backtest engine. Keeping it under `quantarena` matches existing artifact tooling.
  - Alternative considered: extend `backtest.report.ReportGenerator`; rejected because that couples browser UI to run-time report generation and makes viewing old artifacts harder.

- Reuse `load_run_report_artifacts` as the sole file boundary.
  - Rationale: the loader already centralizes required artifact parsing and error reporting.
  - Alternative considered: duplicate CSV/JSON parsing in the visualizer; rejected because it would create parallel artifact semantics.

- Generate vanilla HTML/CSS/JS with embedded JSON and no network dependencies.
  - Rationale: report artifacts should remain portable and viewable from `file://` without CDN availability.
  - Alternative considered: depend on Plotly/React/Vite; rejected because it adds build/runtime dependencies for a simple inspection page.

- Add CLI shape `quantarena report visualize --root <run-dir> --output <html> [--json]`.
  - Rationale: `report` groups generated backtest report utilities separately from release `artifact` validation.

## Risks / Trade-offs

- [Risk] Browser-side visualization is intentionally simple compared with chart libraries. → Mitigation: use SVG for equity/benchmark trend and tables for detailed inspection.
- [Risk] A report directory missing required artifacts cannot be visualized. → Mitigation: return structured errors and do not write partial HTML.
- [Risk] Single-run scope does not compare multiple experiments. → Mitigation: this keeps the first visualization surface small; multi-run comparison can be a later OpenSpec change.
