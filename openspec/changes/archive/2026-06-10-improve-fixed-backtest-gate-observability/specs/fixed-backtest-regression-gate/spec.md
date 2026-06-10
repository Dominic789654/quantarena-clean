## ADDED Requirements

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
