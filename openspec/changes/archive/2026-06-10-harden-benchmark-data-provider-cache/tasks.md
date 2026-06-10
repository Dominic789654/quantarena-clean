## 1. Benchmark Cache

- [x] 1.1 Add a file-backed benchmark daily close cache helper with coverage checks.
- [x] 1.2 Route US index benchmark curve construction through cache before yfinance.
- [x] 1.3 Warm the benchmark cache after successful live yfinance downloads.

## 2. Diagnostics

- [x] 2.1 Add benchmark diagnostics collector and JSONL export in report generation.
- [x] 2.2 Record diagnostics for cache hits, live failures/empty responses, and equal-weight fallback.
- [x] 2.3 Include benchmark diagnostics paths in fixed benchmark summaries when available.

## 3. Verification

- [x] 3.1 Add focused cache, engine, report, and fixed runner tests.
- [x] 3.2 Run OpenSpec validation and focused test suite.
