## 1. Fixed Multi-Personality Runner

- [x] 1.1 Add `multi` mode to the fixed benchmark runner command builder and mode expansion.
- [x] 1.2 Add configurable multi-personality analysts, personality set, max workers, benchmark cache directory, and news replay fixture env propagation.
- [x] 1.3 Add summary fields for news diagnostics and multi-personality artifact review results.

## 2. US Data Source Routing

- [x] 2.1 Prevent US index constituent lookup from constructing or calling Tushare for caret-prefixed US indices.
- [x] 2.2 Add focused tests for US-safe constituent fallback and fixed runner env propagation.

## 3. Verification

- [x] 3.1 Run OpenSpec strict validation.
- [x] 3.2 Run focused unit tests for the fixed runner, benchmark reporting, Smart Beta, and replay news paths.
- [x] 3.3 Run fixed single backtest and fixed multi-personality backtest, then review generated artifacts.
