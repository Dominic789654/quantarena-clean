## ADDED Requirements

### Requirement: Provide Warmup Planning Inputs
The system SHALL expose cache health findings and layer details in a stable
shape that fixed-backtest warmup planning can consume.

#### Scenario: Required cache finding reported
- **WHEN** a required cache layer is missing or insufficiently covered
- **THEN** the health report SHALL include the layer name, cache path or key,
  reason, and per-layer details needed to construct a warmup action.

#### Scenario: Required cache layer ready
- **WHEN** a required cache layer is ready
- **THEN** the health report SHALL include enough per-layer details to explain
  why no warmup action is required.
