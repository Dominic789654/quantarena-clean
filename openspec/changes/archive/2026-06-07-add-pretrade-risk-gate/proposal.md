## Why

The current system can generate research and backtest decisions, but there is no deterministic pre-trade boundary between an LLM decision and an executable order intent. Before any future broker integration, BUY/SELL decisions must be converted through a live-safe risk gate that rejects or adjusts unsafe orders without relying on prompts.

## What Changes

- Add a new pre-trade risk gate capability for converting model `Decision` objects into deterministic `OrderIntent` objects.
- Reject invalid, fallback, over-sized, market-closed, cash-insufficient, and position-insufficient decisions before they can be treated as executable orders.
- Add configuration types for hard limits such as max order notional, max position weight, and price collars.
- Keep the change broker-neutral: no live broker API or real order submission is introduced in this change.

## Capabilities

### New Capabilities
- `pretrade-risk-gate`: Defines deterministic checks required before a model decision may become an executable order intent.

### Modified Capabilities

## Impact

- Adds new trading-domain modules for order intent and pre-trade risk validation.
- Adds focused tests for BUY/SELL/HOLD conversion and rejection reasons.
- Does not change existing backtest execution behavior or connect to any broker.
