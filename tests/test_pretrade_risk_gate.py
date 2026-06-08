from types import SimpleNamespace

from trading import (
    MarketSnapshot,
    OrderSide,
    PortfolioSnapshot,
    PositionSnapshot,
    PreTradeRiskEngine,
    RiskLimits,
    RiskReason,
)


def _decision(action="Buy", shares=10, price=100.0, justification="model"):
    return SimpleNamespace(action=action, shares=shares, price=price, justification=justification)


def _open_market(price=100.0):
    return MarketSnapshot(latest_price=price, is_open=True)


def test_hold_decision_is_approved_without_order():
    result = PreTradeRiskEngine().validate_decision(
        symbol="AAPL",
        decision=_decision(action="Hold", shares=0),
        portfolio=PortfolioSnapshot(cash=1000.0),
        market=_open_market(),
    )

    assert result.approved is True
    assert result.order is None
    assert result.reasons == (RiskReason.HOLD_DECISION,)


def test_invalid_buy_inputs_are_rejected():
    engine = PreTradeRiskEngine()
    portfolio = PortfolioSnapshot(cash=1000.0)
    market = _open_market()

    bad_shares = engine.validate_decision(
        symbol="AAPL",
        decision=_decision(action="Buy", shares=0, price=100.0),
        portfolio=portfolio,
        market=market,
    )
    bad_price = engine.validate_decision(
        symbol="AAPL",
        decision=_decision(action="Buy", shares=1, price=0.0),
        portfolio=portfolio,
        market=market,
    )
    bad_action = engine.validate_decision(
        symbol="AAPL",
        decision=_decision(action="Rebalance", shares=1, price=100.0),
        portfolio=portfolio,
        market=market,
    )

    assert bad_shares.reasons == (RiskReason.INVALID_SHARES,)
    assert bad_price.reasons == (RiskReason.INVALID_PRICE,)
    assert bad_action.reasons == (RiskReason.INVALID_ACTION,)


def test_buy_is_reduced_to_available_cash():
    result = PreTradeRiskEngine().validate_decision(
        symbol="AAPL",
        decision=_decision(action="Buy", shares=10, price=100.0),
        portfolio=PortfolioSnapshot(cash=350.0),
        market=_open_market(),
    )

    assert result.approved is True
    assert result.order is not None
    assert result.order.shares == 3
    assert result.order.side == OrderSide.BUY
    assert result.reasons == (RiskReason.CASH_LIMIT,)


def test_buy_is_rejected_when_cash_cannot_afford_one_share():
    result = PreTradeRiskEngine().validate_decision(
        symbol="AAPL",
        decision=_decision(action="Buy", shares=10, price=100.0),
        portfolio=PortfolioSnapshot(cash=99.0),
        market=_open_market(),
    )

    assert result.rejected is True
    assert result.order is None
    assert result.reasons == (RiskReason.CASH_LIMIT,)


def test_sell_is_reduced_to_held_position():
    result = PreTradeRiskEngine().validate_decision(
        symbol="AAPL",
        decision=_decision(action="Sell", shares=10, price=100.0),
        portfolio=PortfolioSnapshot(cash=0.0, positions={"AAPL": PositionSnapshot(shares=4, market_value=400.0)}),
        market=_open_market(),
    )

    assert result.approved is True
    assert result.order is not None
    assert result.order.shares == 4
    assert result.order.side == OrderSide.SELL
    assert result.reasons == (RiskReason.POSITION_LIMIT,)


def test_sell_is_rejected_when_shorting_is_disabled_and_no_position():
    result = PreTradeRiskEngine().validate_decision(
        symbol="AAPL",
        decision=_decision(action="Sell", shares=1, price=100.0),
        portfolio=PortfolioSnapshot(cash=0.0),
        market=_open_market(),
    )

    assert result.rejected is True
    assert result.reasons == (RiskReason.SHORT_NOT_ALLOWED,)


def test_max_order_notional_reduces_whole_share_quantity():
    engine = PreTradeRiskEngine(RiskLimits(max_order_notional=250.0))

    result = engine.validate_decision(
        symbol="AAPL",
        decision=_decision(action="Buy", shares=10, price=100.0),
        portfolio=PortfolioSnapshot(cash=2000.0),
        market=_open_market(),
    )

    assert result.approved is True
    assert result.order is not None
    assert result.order.shares == 2
    assert result.reasons == (RiskReason.MAX_ORDER_NOTIONAL,)


def test_position_weight_limit_reduces_buy_quantity():
    engine = PreTradeRiskEngine(RiskLimits(max_position_weight=0.20))
    portfolio = PortfolioSnapshot(
        cash=1000.0,
        total_value=2000.0,
        positions={"AAPL": PositionSnapshot(shares=2, market_value=200.0)},
    )

    result = engine.validate_decision(
        symbol="AAPL",
        decision=_decision(action="Buy", shares=10, price=100.0),
        portfolio=portfolio,
        market=_open_market(),
    )

    assert result.approved is True
    assert result.order is not None
    assert result.order.shares == 2
    assert result.reasons == (RiskReason.MAX_POSITION_WEIGHT,)


def test_market_closed_is_rejected_by_default():
    result = PreTradeRiskEngine().validate_decision(
        symbol="AAPL",
        decision=_decision(action="Buy", shares=1, price=100.0),
        portfolio=PortfolioSnapshot(cash=1000.0),
        market=MarketSnapshot(latest_price=100.0, is_open=False),
    )

    assert result.rejected is True
    assert result.reasons == (RiskReason.MARKET_CLOSED,)


def test_price_outside_collar_is_rejected():
    engine = PreTradeRiskEngine(RiskLimits(price_collar_bps=100.0))

    result = engine.validate_decision(
        symbol="AAPL",
        decision=_decision(action="Buy", shares=1, price=103.0),
        portfolio=PortfolioSnapshot(cash=1000.0),
        market=_open_market(price=100.0),
    )

    assert result.rejected is True
    assert result.reasons == (RiskReason.PRICE_COLLAR,)


def test_approved_order_intent_contains_source_and_adjustments():
    result = PreTradeRiskEngine(RiskLimits(max_order_notional=450.0)).validate_decision(
        symbol="aapl",
        decision=_decision(action="Buy", shares=10, price=100.0, justification="bullish"),
        portfolio=PortfolioSnapshot(cash=1000.0),
        market=_open_market(),
    )

    assert result.approved is True
    assert result.order is not None
    assert result.order.symbol == "AAPL"
    assert result.order.source_action == "BUY"
    assert result.order.source_justification == "bullish"
    assert result.order.adjustments == (RiskReason.MAX_ORDER_NOTIONAL,)
    assert result.order.metadata["requested_shares"] == 10
