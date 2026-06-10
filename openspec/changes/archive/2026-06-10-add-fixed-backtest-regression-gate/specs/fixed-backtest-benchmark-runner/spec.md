## ADDED Requirements

### Requirement: Preserve Child Process Logs
The system SHALL preserve complete child backtest stdout and stderr in log files
without embedding unbounded output in the benchmark summary JSON.

#### Scenario: Successful mode writes child logs
- **WHEN** a fixed benchmark mode completes
- **THEN** the summary SHALL include paths to the mode stdout and stderr log
  files and bounded stdout and stderr tail fields for quick debugging.

#### Scenario: Failed mode writes child logs
- **WHEN** a fixed benchmark mode fails
- **THEN** the full child stdout and stderr SHALL still be written to log files
  before the summary is written.

#### Scenario: Summary omits complete child output
- **WHEN** the fixed benchmark summary JSON is written
- **THEN** it SHALL NOT embed complete child stdout or stderr payloads.
