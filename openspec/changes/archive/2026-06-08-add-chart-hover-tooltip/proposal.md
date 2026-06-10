## Why

The static equity chart now renders, but viewers need point-level context when inspecting changes across dates. Hover details make the chart useful for diagnosing daily portfolio and benchmark movement without leaving the page.

## What Changes

- Add browser-side hover tooltip behavior to the equity chart.
- Show nearest date, portfolio value, portfolio daily return, benchmark value, and benchmark return when available.
- Keep the existing static SVG fallback so the chart remains visible when JavaScript does not run.

## Capabilities

### New Capabilities

### Modified Capabilities
- `backtest-html-visualizer`: The equity time-series chart gains interactive hover details while preserving offline/static rendering.

## Impact

- Updates the standalone visualizer HTML/JS renderer and tests.
- Does not change report artifact format, CLI shape, backtest execution, or provider/LLM behavior.
