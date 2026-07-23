## Why

`SharedDataCache._prefetch_deepear_data` (backtest/multi_personality_engine.py) called `DatabaseManager.get_signals_by_date_and_stock`, a method that does not exist — every call raised AttributeError, silently swallowed by the inner except, so `_deepear_cache` was always empty and its getter (`get_deepear_for_ticker_date`) had zero external consumers. Dead weight flagged by the decomposition planning analysis.

## What Changes

- Remove the dead prefetch path entirely: `_prefetch_deepear_data`, `_deepear_cache`, `get_deepear_for_ticker_date`, the `deepear_fetch_time` stat, and its report line. Behavior is identical (the path never produced data).

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `multi-personality-shared-phase-execution`: the shared-data cache no longer advertises a DeepEar prefetch it never performed.

## Impact

- backtest/multi_personality_engine.py only; ~40 lines removed.
