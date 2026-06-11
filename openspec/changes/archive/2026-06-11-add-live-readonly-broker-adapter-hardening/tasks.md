## 1. Live Readonly Hardening

- [x] 1.1 Add read-only capability metadata on the adapter/manager.
- [x] 1.2 Expand smoke health output with provider details, snapshot path, per-step status, counts, and errors.

## 2. Fixtures and Tests

- [x] 2.1 Add a committed live read-only snapshot fixture.
- [x] 2.2 Update broker and CLI tests to assert health metadata, count reporting, failure reporting, and absence of manager mutation facades.

## 3. Validation

- [x] 3.1 Validate the OpenSpec change strictly.
- [x] 3.2 Run targeted live read-only pytest coverage.
