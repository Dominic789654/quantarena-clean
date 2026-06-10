## MODIFIED Requirements

### Requirement: Visualize Portfolio Time Series
The system SHALL visualize portfolio-level time series from `equity_curve.csv` and SHALL expose point-level hover details when browser JavaScript is available.

#### Scenario: Equity and benchmark rows exist
- **WHEN** equity curve rows include `date`, `total_value`, and optional benchmark fields
- **THEN** the generated page SHALL render a browser-side chart data model for portfolio total value and benchmark value.

#### Scenario: Chart hover details
- **WHEN** a viewer hovers over the equity chart and browser JavaScript is enabled
- **THEN** the generated page SHALL show the nearest date, portfolio value, portfolio daily return, benchmark value, and benchmark return when those fields are available.

#### Scenario: JavaScript unavailable
- **WHEN** browser JavaScript does not execute
- **THEN** the generated page SHALL still include the static SVG equity chart generated from the report artifacts.
