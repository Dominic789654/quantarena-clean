## Why

The live read-only adapter is the next step toward real market connectivity, so its inspection boundary needs stronger evidence that it cannot mutate broker state. Health output should also be detailed enough to diagnose provider, snapshot, and per-read failures before adding real broker adapters.

## What Changes

- Add structured read-only capability metadata to live read-only manager and smoke output.
- Expand smoke health details with provider metadata, snapshot path, per-step ok/error status, and read counts.
- Add a committed live snapshot fixture so adapter and CLI tests exercise a reusable provider contract.
- Add regression coverage that the manager exposes no mutating facade and the adapter continues rejecting mutating calls.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-readonly-broker-adapter`: harden health reporting and explicit read-only/mutation-disabled guarantees.

## Impact

- Affects `trading/live_readonly.py`, `quantarena live` smoke output shape, and live-readonly tests.
- No new dependencies.
- No live trading, order submission, cancellation, or broker mutation is introduced.
