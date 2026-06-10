## ADDED Requirements

### Requirement: Keep US Index Routing Off CN-Only Providers
The system SHALL avoid CN-only market data providers when preparing US benchmark or index constituent data.

#### Scenario: US index constituents use US-safe fallback
- **WHEN** Smart Beta requests constituents for a caret-prefixed US index such as `^GSPC`
- **THEN** the index constituents provider SHALL return US-safe fallback constituents without constructing or calling Tushare.

#### Scenario: US index benchmark cache remains first
- **WHEN** a US benchmark curve request has cached close prices covering the requested trading days
- **THEN** the system SHALL build the benchmark curve from cache before importing or calling a live provider.
