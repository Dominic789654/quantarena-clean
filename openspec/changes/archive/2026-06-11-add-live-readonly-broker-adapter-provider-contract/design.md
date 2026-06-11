## Context

The live read-only adapter currently supports a snapshot provider and reports read-only health metadata. Before adding a real broker API adapter, the project needs an executable provider contract that specifies which methods and payload fields every live read-only provider must implement and how provider-level failures are reported.

## Goals / Non-Goals

**Goals:**

- Define a provider contract that applies to snapshot and future real broker providers.
- Validate normalized account, position, order, and quote payloads through a local contract check.
- Report credential and rate-limit failures with stable machine-readable error categories.
- Keep the CLI inspection-only and mutation-free.

**Non-Goals:**

- Add Alpaca, Interactive Brokers, Futu, or any other real broker integration.
- Fetch real account data over the network.
- Add live order submission, cancellation, fill handling, or trading.

## Decisions

- Implement the contract as reusable validation helpers in `trading.live_readonly` instead of creating a separate package. This keeps the read-only boundary, adapter construction, health checks, and contract validation in one module while the surface is still small.
- Validate payload shape after reads rather than relying only on static typing. Real broker adapters will normalize external API responses at runtime, so contract checks must inspect actual JSON-ready payloads.
- Introduce stable error categories such as `credential_missing`, `rate_limited`, `provider_error`, and `schema_error`. These categories are more useful to automation than provider-specific exception classes.
- Add a `quantarena live contract` command. It reuses the existing provider configuration and returns JSON only, matching the current `quantarena live` command style.

## Risks / Trade-offs

- [Risk] The contract checker reads all four provider surfaces and may be slower for real brokers. → Mitigation: it is an explicit diagnostic command, not part of hot-path trading.
- [Risk] Provider-specific fields may vary. → Mitigation: the contract requires only broker-neutral normalized fields and allows extra metadata in provider payloads.
- [Risk] Credential/rate-limit detection can be provider-specific. → Mitigation: start with stable local exception categories and keep provider adapters responsible for mapping their native errors into these categories.
