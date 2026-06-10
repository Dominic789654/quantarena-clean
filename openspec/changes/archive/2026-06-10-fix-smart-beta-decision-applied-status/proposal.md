## Why

The latest five-personality backtest exported complete daily decision rows, but every `smart_beta_passive` row had `applied=null` while other personalities exported explicit booleans. This weakens downstream artifact checks because consumers cannot distinguish "not yet applied" from "missing metadata".

## What Changes

- Mark Smart Beta generated decisions with explicit `_applied` metadata before execution.
- Preserve `_applied=False` for Smart Beta decisions that still need the base execution path to apply them.
- Keep already-applied specialized and LLM paths unchanged.
- Add focused tests that prevent daily decision exports from regressing to `applied=null` for Smart Beta.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `multi-personality-shared-phase-execution`: daily decision artifacts must include explicit applied-state metadata for Smart Beta decisions.

## Impact

- Updates `backtest.smart_beta_engine` decision output.
- Adds/updates Smart Beta and multi-personality artifact tests.
- Requires single Smart Beta backtest and five-personality backtest verification after implementation.
