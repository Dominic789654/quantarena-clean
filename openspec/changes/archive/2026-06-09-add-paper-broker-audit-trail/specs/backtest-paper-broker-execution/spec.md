## ADDED Requirements

### Requirement: Export Backtest Paper Broker Audit Trail
The system SHALL include a paper broker audit artifact in each generated backtest report directory while preserving existing trade, equity, metrics, and dashboard contracts.

#### Scenario: Report includes audit path
- **WHEN** full backtest report generation completes
- **THEN** the returned report path mapping SHALL include `broker_audit_jsonl` pointing to `broker_audit.jsonl`.

#### Scenario: Existing artifacts remain unchanged
- **WHEN** the audit artifact is generated
- **THEN** existing `trades.csv`, `metrics.json`, `equity_curve.csv`, and dashboard inputs SHALL remain backward compatible.
