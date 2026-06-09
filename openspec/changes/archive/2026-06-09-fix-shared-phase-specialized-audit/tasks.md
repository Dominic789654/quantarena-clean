## 1. Execution Path

- [x] 1.1 Add or adapt the precollected-signal decision hook so `fundamental_value` applies value filters in shared phase-1 mode.
- [x] 1.2 Add or adapt the precollected-signal decision hook so `behavioral_momentum` applies momentum controls in shared phase-1 mode.
- [x] 1.3 Route direct smart-priority LLM BUY/SELL decisions through paper broker execution helpers so audit events are generated.

## 2. Regression Coverage

- [x] 2.1 Add tests for shared-phase specialized personality hooks using precollected signals without recomputing phase 1.
- [x] 2.2 Add tests that smart-priority LLM decisions produce matching trades and broker audit events.
- [x] 2.3 Add or document an artifact-review command/check for trades versus `broker_audit.jsonl` and specialized metrics.

## 3. Verification

- [x] 3.1 Run targeted unit tests for the changed execution paths.
- [x] 3.2 Run a short multi-personality backtest or deterministic substitute and inspect logs/artifacts for the previous failure mode.
- [x] 3.3 Validate and archive the OpenSpec change when implementation and verification pass.
