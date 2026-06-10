## Why

Backtest reports are currently split across Markdown, CSV, PNG, and JSON artifacts, which makes single-stock and multi-stock inspection cumbersome after a run. A self-contained HTML visualizer gives researchers a stable offline page for reviewing equity, benchmark, trades, positions, and ticker-level behavior from existing report artifacts.

## What Changes

- Add a report visualization capability that renders generated backtest artifacts into one static HTML page.
- Add a CLI entry point for generating the HTML page from a report directory without rerunning the backtest.
- Embed run metrics, equity curve, trades, and final positions as JSON for offline browser inspection.
- Support all-ticker and single-ticker views for trades and final positions.
- Keep the visualizer read-only: it must not call market-data providers, LLM APIs, or mutate report artifacts other than writing the requested HTML output file.

## Capabilities

### New Capabilities
- `backtest-html-visualizer`: Defines generation and behavior of offline HTML pages for inspecting backtest result artifacts.

### Modified Capabilities

## Impact

- Adds a pure HTML visualizer renderer under `quantarena`.
- Extends the stable CLI with a report visualization command.
- Adds focused tests using synthetic report artifacts.
- Does not change backtest execution, report generation, or provider/LLM behavior.
