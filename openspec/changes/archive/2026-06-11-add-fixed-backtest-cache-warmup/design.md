## Context

The fixed cache health report can say whether deterministic backtest inputs are
ready, but operators still have to translate findings into next steps. This
change adds a planning layer on top of the existing read-only health report so
the workflow can be: health check → warmup plan → fixed regression gate.

## Goals / Non-Goals

**Goals:**
- Produce a fixed-backtest warmup plan from cache health results.
- Keep the default behavior read-only and deterministic.
- Provide JSON and human-readable CLI output.
- Make strict mode fail when required warmup actions remain.

**Non-Goals:**
- Do not download live market data in this change.
- Do not write stock-price, benchmark, or news fixture caches.
- Do not replace cache health reports or fixed regression gates.

## Decisions

1. Build warmup planning on top of `CacheHealthReport`.
   - Rationale: cache health already knows paths, layers, and reasons. Reusing it
     keeps one source of truth for readiness.
   - Alternative considered: duplicate checks in a new module. That would drift
     from health behavior and make failures inconsistent.

2. Use action records instead of free-form text only.
   - Rationale: later changes can convert action records into real `--write`
     behavior, CI annotations, or documentation.
   - Alternative considered: only print human instructions. That would be less
     useful for automation.

3. Keep action execution out of scope.
   - Rationale: writes and provider downloads require credential and data-source
     policy decisions. A planning-only command is immediately useful and safe.
   - Alternative considered: add `--write-missing` now. That would widen the
     blast radius and mix cache preparation with provider integration.

## Risks / Trade-offs

- [Risk] Warmup actions are advisory, so users still need a separate command to
  populate missing caches. → Mitigation: include recommended next command or
  provider step in every action.
- [Risk] Plan output can become stale if health finding shapes change. →
  Mitigation: add explicit cache-health spec requirements and tests for the
  fields consumed by warmup planning.
