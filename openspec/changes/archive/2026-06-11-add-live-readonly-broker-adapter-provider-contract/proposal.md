## Why

The live read-only adapter now has a safe snapshot boundary, but future real broker providers still need a concrete contract before any broker-specific integration is added. Locking the provider contract first prevents provider drift, ambiguous errors, and accidental mutation surfaces when moving from fixture snapshots to real account APIs.

## What Changes

- Define a live read-only provider contract for required read methods, normalized payload fields, read-only capabilities, and no mutation support.
- Add machine-readable provider contract validation for account, positions, orders, quotes, credentials, and rate-limit/error reporting.
- Expose a local CLI contract check that validates a configured provider without submitting or cancelling orders.
- Add tests that validate snapshot provider contract compliance and expected failure reporting.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-readonly-broker-adapter`: add provider contract validation requirements for future real broker adapters.

## Impact

- Affects `trading/live_readonly.py`, `quantarena live` CLI surface, and live read-only tests.
- No external broker dependency is introduced.
- No live trading, order submission, cancellation, or broker mutation is introduced.
