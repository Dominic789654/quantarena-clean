## ADDED Requirements

### Requirement: Generate Offline Backtest HTML
The system SHALL generate a standalone HTML page from an existing backtest report artifact directory without rerunning the backtest.

#### Scenario: Valid report directory
- **WHEN** a report directory contains `metrics.json`, `equity_curve.csv`, and `trades.csv`
- **THEN** the visualizer SHALL write an HTML file containing embedded run metrics, equity curve rows, trade rows, and final positions.

#### Scenario: Missing required artifact
- **WHEN** a report directory is missing a required artifact
- **THEN** the visualizer SHALL report structured errors and SHALL NOT write a partial HTML page.

### Requirement: Inspect Single And Multiple Tickers
The system SHALL support all-ticker and single-ticker inspection in the generated HTML page.

#### Scenario: Multi-stock run
- **WHEN** the report artifacts contain multiple tickers
- **THEN** the generated HTML SHALL include ticker controls for viewing all tickers or an individual ticker.

#### Scenario: Single-stock filter
- **WHEN** a viewer selects one ticker in the generated page
- **THEN** trade and final-position tables SHALL show only rows for that ticker while preserving portfolio-level summary metrics.

### Requirement: Visualize Portfolio Time Series
The system SHALL visualize portfolio-level time series from `equity_curve.csv`.

#### Scenario: Equity and benchmark rows exist
- **WHEN** equity curve rows include `date`, `total_value`, and optional benchmark fields
- **THEN** the generated page SHALL render a browser-side chart data model for portfolio total value and benchmark value.

### Requirement: CLI Report Visualization
The system SHALL expose HTML report generation through the stable QuantArena CLI.

#### Scenario: CLI visualization succeeds
- **WHEN** a user runs `quantarena report visualize --root <run-dir> --output <html>` for a valid report directory
- **THEN** the command SHALL write the HTML file and exit successfully.

#### Scenario: CLI JSON output
- **WHEN** the user passes `--json`
- **THEN** the command SHALL print a machine-readable payload containing `ok`, `output`, `run_id`, `tickers`, and any errors.
