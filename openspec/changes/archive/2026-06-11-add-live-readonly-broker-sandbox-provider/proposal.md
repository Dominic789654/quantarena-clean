## Why

The live read-only provider contract is in place, but only the static snapshot provider currently exercises it. A local paper-sandbox provider gives the live read-only interface a state-backed provider that behaves closer to an account adapter while remaining offline and mutation-safe.

## What Changes

- Add a `paper_sandbox` live read-only provider that reads account, positions, orders, and quotes from the existing paper portfolio state file.
- Allow `quantarena live --provider paper_sandbox --paper-state <path>` to run account, positions, orders, quotes, smoke, and contract checks.
- Keep all paper-sandbox access read-only from the live interface; no paper init, quote set, submit, fill, or cancel commands are exposed through `quantarena live`.
- Add tests proving the paper-sandbox provider satisfies the live read-only provider contract and does not mutate the paper state file.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-readonly-broker-adapter`: add a local paper-sandbox read-only provider.

## Impact

- Affects `trading/live_readonly.py`, `quantarena live` CLI options, and live read-only tests.
- Reuses existing paper portfolio state serialization; no new dependencies.
- Does not add real broker network access or live trading.
