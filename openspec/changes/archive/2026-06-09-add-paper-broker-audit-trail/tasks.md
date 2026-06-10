## 1. Audit event capture

- [x] 1.1 Add audit event creation helpers for filled and rejected execution attempts.
- [x] 1.2 Preserve monotonic paper order/fill sequences across backtest execution helper calls.
- [x] 1.3 Wire `BacktestEngine` to collect broker audit events from direct and target-allocation execution.

## 2. Report artifact export

- [x] 2.1 Add `broker_audit.jsonl` generation to the report writer.
- [x] 2.2 Include the audit artifact path in full report path mappings.
- [x] 2.3 Update report artifact loader support for optional audit events.

## 3. Tests and validation

- [x] 3.1 Add execution helper tests for filled audit events and risk-gate rejection events.
- [x] 3.2 Add report generation tests for `broker_audit.jsonl`.
- [x] 3.3 Run focused pytest, paper smoke, fixed benchmark smoke, and OpenSpec validation.
- [x] 3.4 Archive the OpenSpec change.
