## 1. Regression Gate

- [x] 1.1 Add a committed fixed benchmark baseline fixture with metric tolerances and diagnostic expectations.
- [x] 1.2 Implement fixed summary baseline evaluation with structured pass/fail findings.
- [x] 1.3 Add a CLI workflow that evaluates an existing summary or runs the fixed benchmark before evaluation.

## 2. Runner Log Artifacts

- [x] 2.1 Write per-mode child stdout and stderr logs under the benchmark summary directory.
- [x] 2.2 Replace complete stdout and stderr summary fields with log paths and bounded tails.

## 3. Regression Coverage

- [x] 3.1 Add focused tests for baseline metric failures, missing modes, diagnostics checks, and CLI behavior.
- [x] 3.2 Update fixed benchmark runner tests for externalized child logs.

## 4. Verification

- [x] 4.1 Run OpenSpec strict validation and focused pytest coverage.
- [x] 4.2 Run fixed simple and fixed multi-personality regression gates with deterministic fixtures.
