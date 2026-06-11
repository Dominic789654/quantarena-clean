## Context

The fixed benchmark path now depends on multiple deterministic data controls:
stock prices in the local backtest database, benchmark closes in a JSONL cache,
and replay news fixtures. The project also has multi-personality shared cache
directories, but the immediate need is a read-only report that answers whether a
fixed benchmark run will use prepared inputs or fall through to live providers.

## Goals / Non-Goals

**Goals:**
- Provide one read-only report for fixed benchmark cache readiness.
- Make cache misses actionable with layer, path/key, and reason fields.
- Offer JSON output for automation and concise human output for local use.
- Keep strict failure behavior opt-in.

**Non-Goals:**
- Do not download missing data or write cache files.
- Do not replace fixed regression gate checks.
- Do not validate every possible provider cache in the repository on the first
  iteration.

## Decisions

1. Implement the report as a `quantarena.cache_health` module plus CLI wiring.
   - Rationale: existing engineering utilities live under `quantarena`, and the
     CLI can reuse a stable module API in tests and scripts.
   - Alternative considered: add logic directly to the fixed backtest runner.
     That would couple cache diagnostics to one runner instead of making it
     reusable.

2. Start with a fixed-backtest profile and explicit inputs.
   - Rationale: the current deterministic benchmark is the highest-value
     workflow and has known tickers, dates, benchmark index, and replay fixture.
   - Alternative considered: auto-discover all cache directories. That is noisy
     and less actionable without profile-specific expectations.

3. Check stock-price coverage through the existing database manager API when a
   database path is available.
   - Rationale: this matches the backtest data loader's cache source and avoids
     duplicating SQLite schema details.
   - Alternative considered: parse SQLite directly. That would create an
     unnecessary second database access path.

4. Treat shared cache directory presence as informational for this change.
   - Rationale: fixed simple runs do not require shared phase caches, and
     shared caches are recreated by multi runs. The report should show their
     state without blocking strict fixed profile checks.

## Risks / Trade-offs

- [Risk] Different local environments may use different database paths. →
  Mitigation: accept an explicit `--db-path` and default to the existing
  `data/signal_flux.db`.
- [Risk] Trading-day coverage uses the requested date list rather than exchange
  calendar validation. → Mitigation: fixed benchmark dates are already known and
  aligned with the regression fixture.
- [Risk] News replay fixture validation might pass a file with irrelevant rows.
  → Mitigation: require parseable rows and at least one row matching fixed
  tickers or dates; deeper per-day news coverage can be a later warmup change.
