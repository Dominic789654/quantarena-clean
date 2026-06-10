## Context

The fixed backtest regression gate currently returns `ok`, paths, profile, and
failure findings. That is enough for CI-style pass/fail checks, but it does not
show which baseline checks were exercised on a passing run. Child process logs
are correctly externalized, yet normal INFO/DEBUG log volume makes warnings and
errors hard to find without opening full log files.

## Goals / Non-Goals

**Goals:**
- Make passing gate output auditable by summarizing evaluated checks.
- Surface bounded warning/error evidence from referenced child logs.
- Keep existing pass/fail semantics and baseline tolerance behavior unchanged.

**Non-Goals:**
- Do not classify routine INFO/DEBUG lines as failures.
- Do not add new baseline thresholds in this change.
- Do not rewrite log routing in the backtest runner.

## Decisions

1. Add observability fields to `FixedBacktestGateResult`.
   - Rationale: callers already consume one gate result object, so this avoids a
     second report file or separate CLI.
   - Alternative considered: write a sibling diagnostics JSON file. That adds
     another artifact to find and keep in sync.

2. Count checks from the baseline expectations while evaluating each mode.
   - Rationale: the baseline is the authoritative source of what the gate should
     check, and the summary can record what was actually available.
   - Alternative considered: infer coverage from findings. Passing runs have no
     findings, so inference would be incomplete.

3. Extract warning/error log issues with conservative text matching and a hard
   per-stream cap.
   - Rationale: this gives a useful first scan while preventing huge log payloads
     from re-entering the gate result.
   - Alternative considered: fail the gate on warnings. Current logs include
     dependency warnings that are worth seeing but should not become regression
     failures without a separate baseline rule.

## Risks / Trade-offs

- [Risk] Text matching can miss unusual warning formats. → Mitigation: match
  common `WARNING`, `WARN`, `ERROR`, `Traceback`, and Python warning patterns,
  while retaining links to full logs.
- [Risk] Gate JSON grows with log issue entries. → Mitigation: cap issue entries
  per stream and keep messages to single log lines.
