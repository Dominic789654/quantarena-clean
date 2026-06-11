## Why

QuantArena now relies on several cache layers for deterministic fixed backtests:
stock-price DB cache, benchmark close-price cache, news replay fixtures, and
multi-personality shared artifact caches. Before moving further toward real
market workflows, users need one report that explains which cache inputs are
ready and which missing inputs would trigger live providers or nondeterminism.

## What Changes

- Add a cache health report that inspects configured cache layers without
  fetching live data.
- Support a fixed-backtest profile for AAPL, MSFT, NVDA, `^GSPC`, and the
  existing replay news fixture.
- Report per-layer status, required paths, row counts or coverage, and
  machine-readable findings.
- Add a CLI entrypoint for JSON and human-readable output, with strict mode for
  failing on cache misses.

## Capabilities

### New Capabilities
- `cache-health-report`: Reports cache readiness across fixed backtest market
  data, benchmark data, news replay fixtures, and shared cache directories.

### Modified Capabilities

## Impact

- Affected code: new cache health report module, CLI integration, tests, and
  OpenSpec specs.
- No network calls, no strategy behavior changes, and no modifications to cache
  contents.
