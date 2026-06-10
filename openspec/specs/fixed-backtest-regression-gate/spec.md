# fixed-backtest-regression-gate Specification

## Purpose
TBD - created by archiving change add-fixed-backtest-regression-gate. Update Purpose after archive.
## Requirements
### Requirement: Evaluate Fixed Backtest Baselines
The system SHALL compare fixed backtest benchmark summaries against a
machine-readable baseline with explicit tolerances.

#### Scenario: Summary matches baseline
- **WHEN** the regression gate evaluates a fixed benchmark summary whose
  requested modes, success status, metrics, and required artifacts match the
  configured baseline tolerances
- **THEN** the gate SHALL report success with zero findings.

#### Scenario: Metric exceeds tolerance
- **WHEN** a numeric metric in the summary differs from its baseline value by
  more than the configured absolute tolerance
- **THEN** the gate SHALL report a failure identifying the mode, metric path,
  actual value, expected value, and tolerance.

#### Scenario: Required mode is missing
- **WHEN** the baseline requires a mode that is absent from the summary
- **THEN** the gate SHALL report a failure identifying the missing mode.

### Requirement: Validate Fixed Artifact Diagnostics
The system SHALL validate fixed simple and fixed multi-personality artifact
diagnostics that are required for deterministic benchmark confidence.

#### Scenario: Multi artifact review fails
- **WHEN** a baseline requires a multi-personality artifact review to be ok and
  the summary artifact review is missing or not ok
- **THEN** the gate SHALL report a failure for the multi mode.

#### Scenario: News diagnostics are required
- **WHEN** a baseline requires nonzero news diagnostics for a mode
- **THEN** the gate SHALL fail if no referenced news diagnostics file contains
  rows with positive final article counts.

#### Scenario: Benchmark cache hit is required
- **WHEN** a baseline requires a benchmark diagnostics cache hit for an index
- **THEN** the gate SHALL fail if no referenced benchmark diagnostics file
  contains a matching index code with provider `cache` and status `hit`.

### Requirement: Run Fixed Gate From CLI
The system SHALL provide a command-line workflow that can evaluate an existing
fixed benchmark summary or run the fixed benchmark before evaluation.

#### Scenario: Evaluate existing summary
- **WHEN** the gate CLI is invoked with a summary path and baseline path
- **THEN** it SHALL evaluate that summary, print a machine-readable gate result
  when JSON output is requested, and exit zero only when the gate passes.

#### Scenario: Run benchmark then evaluate
- **WHEN** the gate CLI is invoked with a fixed benchmark mode instead of an
  existing summary path
- **THEN** it SHALL run the fixed benchmark with the provided deterministic
  data-source controls and evaluate the generated summary against the baseline.

### Requirement: Report Checked Gate Coverage
The system SHALL include a machine-readable checked-summary payload in fixed
backtest regression gate results.

#### Scenario: Passing gate reports evaluated checks
- **WHEN** the regression gate evaluates a summary successfully
- **THEN** the result SHALL include evaluated modes, metric check counts,
  required personalities, diagnostics checks, and referenced log paths.

#### Scenario: Failing gate preserves checked coverage
- **WHEN** the regression gate reports one or more findings
- **THEN** the result SHALL still include checked-summary coverage for every
  mode that was available for evaluation.

### Requirement: Summarize Child Log Issues
The system SHALL extract bounded warning and error evidence from referenced
fixed benchmark child process logs.

#### Scenario: Child logs contain warning or error lines
- **WHEN** a run references stdout or stderr log files containing warning or
  error lines
- **THEN** the gate result SHALL include bounded log issue entries with mode,
  stream, source path, line number, severity, and message.

#### Scenario: Child logs contain only routine lines
- **WHEN** a run references stdout or stderr log files without warning or error
  lines
- **THEN** the gate result SHALL include an empty log issue list and preserve
  normal pass/fail semantics.
