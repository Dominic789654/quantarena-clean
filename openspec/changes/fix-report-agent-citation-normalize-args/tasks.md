## 1. Fix

- [ ] 1.1 Pass `key_to_num` at `deepear/src/agents/report_agent.py:970`, matching lines 999/1204.

## 2. Regression test

- [ ] 2.1 Build minimal FakeModel/FakeAgent/FakeDatabaseManager stubs (monkeypatch-scoped, no sys.modules replacement).
- [ ] 2.2 Test: `ReportAgent(db_stub, model_stub, incremental_edit=False)` + `generate_report(signals)` with 2 short signals (< 80k chars joined) completes and the output contains normalized citation markers.

## 3. Verification

- [ ] 3.1 Full suite green at baseline; ruff clean; CI green.
