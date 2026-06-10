## Context

The pre-trade risk gate now exists as a broker-neutral `trading` package, but `backtest/execution.py` still performs its own cash/share logic before mutating simulated portfolio state. That keeps the current backtest safe from some over-sized trades, but it duplicates the safety logic and does not expose risk-gate reasons on simulated decisions.

## Goals / Non-Goals

**Goals:**
- Use `PreTradeRiskEngine` inside backtest execution helpers before applying simulated BUY/SELL trades.
- Preserve existing successful trade behavior for valid cash/position-limited backtests.
- Attach risk-gate reasons to returned target-weight decisions for observability.
- Keep the backtest market-session requirement disabled, because historical backtest dates are already derived from trading-day data.

**Non-Goals:**
- Add broker submission, paper broker order lifecycle, or live trading mode.
- Change strategy signal generation, LLM prompts, or allocation logic.
- Enforce live-only limits such as market-open, price-collar, or max-notional by default in historical backtests.

## Decisions

- Integrate at `backtest/execution.py` helper boundaries.
  - Rationale: all normal backtest BUY/SELL applications funnel through `execute_buy_order`, `execute_sell_order`, or `convert_targets_to_trades` target conversion. This centralizes the safety boundary without changing strategy engines.
  - Alternative considered: modify each strategy engine independently; rejected because it would duplicate risk validation and miss future engines.

- Use `RiskLimits(require_market_open=False)` for backtest defaults.
  - Rationale: historical simulations are driven by cached trading days and do not have a live market session state. Live/paper execution can enable market-open enforcement later.

- Treat rejected target trades as HOLD with `_risk_reasons`.
  - Rationale: target conversion already returns applied decisions and must not execute rejected trades. Exposing reasons preserves auditability without changing downstream decision shape.

- Keep direct `execute_buy_order` / `execute_sell_order` return type as `bool`.
  - Rationale: existing callers/tests expect boolean application status. Risk reason details are surfaced through warnings for direct helpers and structured fields for target decisions.

## Risks / Trade-offs

- [Risk] Direct helper callers only get risk details through warning strings. → Mitigation: target-weight decisions carry `_risk_reasons`; future integration can return richer execution result objects.
- [Risk] Backtest default limits remain permissive beyond cash/position validity. → Mitigation: this intentionally preserves existing strategy behavior while routing core checks through the same gate.
- [Risk] Zero-price liquidation behavior changes from selling at zero to rejection/HOLD. → Mitigation: non-positive prices are invalid under the pre-trade spec and should not create simulated trades.
