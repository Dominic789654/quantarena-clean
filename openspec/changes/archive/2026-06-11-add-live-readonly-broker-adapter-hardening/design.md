## Context

The existing live read-only adapter supports a snapshot provider plus account, positions, orders, quotes, and smoke commands. It already rejects known mutation methods, but the health output does not make the read-only boundary or read counts explicit enough for future real broker provider parity.

## Goals / Non-Goals

**Goals:**

- Make read-only capability metadata machine-readable.
- Make smoke output useful for diagnosing each read path independently.
- Add a committed snapshot fixture that future live provider tests can share.
- Preserve the current no-live-trading boundary.

**Non-Goals:**

- Add a real broker API provider.
- Add order submission, cancellation, fills, or live trading.
- Change the `quantarena live` command names.

## Decisions

- Keep the hardening inside `LiveReadonlyBrokerManager` and `SnapshotLiveReadonlyBrokerAdapter` instead of adding a separate health service. The current surface is small, and centralizing metadata keeps CLI and tests consistent.
- Return explicit metadata fields such as `readonly=true`, `mutation_allowed=false`, `provider`, and `snapshot_path` in read command and smoke results. This makes the boundary visible to downstream automation without requiring class introspection.
- Represent smoke checks as per-step dictionaries containing `ok`, `command`, `count` where applicable, and `error` when a step fails. This preserves the existing `steps` structure while making it more diagnostic.
- Use a repository fixture under `tests/fixtures/live_readonly/` instead of generating every snapshot inline. Inline generation can still be used for edge cases, but the fixture becomes the contract sample.

## Risks / Trade-offs

- Existing consumers of `quantarena live smoke` may see additional result fields. This is additive JSON, so existing field lookups should continue working.
- Snapshot path output can expose a local path in diagnostics. This command is developer-facing and local; the value is useful for reproducibility.
