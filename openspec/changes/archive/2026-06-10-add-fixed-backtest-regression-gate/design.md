## Context

The fixed benchmark runner can execute deterministic simple and
multi-personality backtests with replay news and benchmark cache fixtures. The
remaining gap is that correctness is still checked manually by reading summary
JSON and logs. The summary also embeds complete child stdout and stderr, which
can grow quickly and makes gate artifacts noisy.

## Goals / Non-Goals

**Goals:**
- Add a deterministic regression gate for fixed benchmark summaries.
- Cover the signals that caught recent issues: run success, metrics drift,
  multi artifact review, news diagnostics, and benchmark cache diagnostics.
- Allow both "evaluate an existing summary" and "run then evaluate" workflows.
- Keep child process logs available while keeping summary JSON bounded.

**Non-Goals:**
- Do not change strategy logic, benchmark dates, fixtures, or portfolio
  semantics.
- Do not add live market or broker behavior.
- Do not enforce a single global CI policy; the gate remains a callable tool.

## Decisions

1. Store the baseline as JSON under the fixed benchmark fixture tree.
   - Rationale: the baseline is test data tied to deterministic replay/cache
     fixtures, not production configuration.
   - Alternative considered: hard-code expectations in Python. That would make
     updates harder to review and reuse outside tests.

2. Compare metrics through named JSON paths with absolute tolerances.
   - Rationale: fixed one-week runs are deterministic with fixtures, but this
     keeps small formatting/rounding differences from creating noisy failures.
   - Alternative considered: hash the full summary. That would be too brittle
     because paths and run ids legitimately change per run.

3. Read diagnostics from the paths already referenced in the runner summary.
   - Rationale: this validates the real artifacts the user will inspect after a
     run instead of duplicating discovery logic in the gate.
   - Alternative considered: inspect report directories directly. That would
     couple the gate to each report layout and make multi-personality runs more
     fragile.

4. Write child stdout/stderr logs under the fixed benchmark summary directory.
   - Rationale: the benchmark-level summary directory is the stable parent
     artifact for the gate and can keep per-mode command logs together.
   - Alternative considered: write logs into child report directories. Failed
     runs may not create a report directory, so that would lose logs exactly
     when they are most useful.

## Risks / Trade-offs

- [Risk] Baseline tolerances can hide real regressions if set too wide. →
  Mitigation: use tight tolerances for deterministic fixture-backed runs and
  keep required diagnostics explicit.
- [Risk] The "run then evaluate" path may be slower than focused unit tests. →
  Mitigation: keep unit coverage for gate logic and use the CLI for full fixed
  benchmark verification.
- [Risk] Existing tools may expect `stdout` and `stderr` fields in summary JSON.
  → Mitigation: preserve concise tail fields and log paths in the same per-run
  object, and keep in-memory dataclass fields for internal parsing.

## Migration Plan

1. Add the gate module, baseline fixture, and CLI wrapper.
2. Update fixed runner summaries to externalize child logs.
3. Add focused tests for baseline comparison, CLI wiring, and log summary shape.
4. Run OpenSpec validation, focused tests, fixed simple gate, and fixed multi
   gate.

## Open Questions

- None.
