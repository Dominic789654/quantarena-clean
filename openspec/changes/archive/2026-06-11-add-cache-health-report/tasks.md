## 1. Cache Health Module

- [x] 1.1 Add cache health report data structures and fixed-backtest profile defaults.
- [x] 1.2 Implement stock-price DB cache, benchmark JSONL cache, replay news fixture, and shared cache directory checks.

## 2. CLI Integration

- [x] 2.1 Add `quantarena cache health` CLI with JSON, strict, and fixed-profile options.
- [x] 2.2 Add a script wrapper for direct local execution.

## 3. Regression Coverage

- [x] 3.1 Add focused tests for ready and missing cache health scenarios.
- [x] 3.2 Add CLI tests for JSON and strict exit behavior.

## 4. Verification

- [x] 4.1 Run OpenSpec strict validation and focused pytest coverage.
- [x] 4.2 Run cache health against the fixed backtest fixtures and current local cache.
