## Context

The live read-only adapter now has a provider contract, and the project already has a persistent local paper portfolio state format. A paper-sandbox provider can reuse that state as a local account-like source for live read-only account, position, order, and quote reads without adding any external broker dependency.

## Goals / Non-Goals

**Goals:**

- Add a `paper_sandbox` provider under the live read-only adapter factory.
- Read broker-neutral account, positions, orders, and quotes from an existing paper portfolio state file.
- Validate the provider with the live read-only provider contract.
- Prove the live interface does not mutate the paper state file.

**Non-Goals:**

- Add a real broker integration or network calls.
- Add paper portfolio write commands to `quantarena live`.
- Replace the existing `quantarena paper` command surface.

## Decisions

- Add `paper_state_path` to `LiveReadonlyConfig` rather than overloading `snapshot_path`. The two providers read different file formats, so explicit configuration keeps diagnostics clear.
- Implement a `PaperSandboxLiveReadonlyBrokerAdapter` that loads the paper broker from state for each read. This avoids caching stale state and keeps the adapter naturally read-only.
- Reuse paper portfolio serialization helpers to normalize payloads instead of duplicating order/account formatting logic where possible.
- Expose `--paper-state` only on `quantarena live`; mutating paper operations remain available only through `quantarena paper`.

## Risks / Trade-offs

- [Risk] Loading the state file on each read is less efficient. → Mitigation: the file is local and the provider is diagnostic/read-only; correctness and freshness matter more.
- [Risk] Users may confuse paper sandbox with real broker sandbox. → Mitigation: provider name and CLI option explicitly refer to local paper state, and no network credentials are accepted.
- [Risk] Paper state schema changes could affect live reads. → Mitigation: reuse `broker_from_state`, so schema validation remains centralized.
