"""Tests for paper broker order lifecycle."""

from __future__ import annotations

import pytest

from trading import (
    BrokerOrderStatus,
    InMemoryOrderStore,
    OrderIntent,
    OrderSide,
    PaperBroker,
    Quote,
    reconcile_account,
)


def test_submit_buy_order_and_fill_updates_cash_and_position():
    broker = PaperBroker(initial_cash=1000.0, quotes={"AAPL": 100.0})
    order = broker.submit_order(_intent("AAPL", OrderSide.BUY, 3, 100.0))

    result = broker.fill_order(order.order_id)

    assert order.status == BrokerOrderStatus.ACCEPTED
    assert result.ok is True
    assert result.order.status == BrokerOrderStatus.FILLED
    assert result.order.filled_quantity == 3
    assert broker.get_account().cash == 700.0
    assert broker.positions["AAPL"] == 3
    assert broker.get_positions()[0].market_value == 300.0
    assert result.fill is not None
    assert result.fill.notional == 300.0


def test_submit_sell_order_and_fill_updates_cash_and_position():
    broker = PaperBroker(initial_cash=1000.0, positions={"AAPL": 5}, quotes={"AAPL": 100.0})
    order = broker.submit_order(_intent("AAPL", OrderSide.SELL, 2, 110.0))

    result = broker.fill_order(order.order_id, price=110.0)

    assert result.ok is True
    assert result.order.status == BrokerOrderStatus.FILLED
    assert broker.get_account().cash == 1220.0
    assert broker.positions["AAPL"] == 3
    assert broker.get_positions()[0].market_value == 330.0


def test_partial_fill_preserves_remaining_quantity_then_full_fill():
    broker = PaperBroker(initial_cash=1000.0)
    order = broker.submit_order(_intent("MSFT", OrderSide.BUY, 5, 20.0))

    first = broker.fill_order(order.order_id, quantity=2, price=20.0)
    second = broker.fill_order(order.order_id, quantity=3, price=21.0)

    assert first.ok is True
    assert first.order.status == BrokerOrderStatus.PARTIAL_FILLED
    assert first.order.remaining_quantity == 3
    assert second.ok is True
    assert second.order.status == BrokerOrderStatus.FILLED
    assert second.order.filled_quantity == 5
    assert broker.positions["MSFT"] == 5
    assert broker.get_account().cash == 897.0


def test_invalid_intent_is_rejected_without_account_change():
    broker = PaperBroker(initial_cash=1000.0)
    order = broker.submit_order(_intent("AAPL", OrderSide.BUY, 0, 100.0))

    assert order.status == BrokerOrderStatus.REJECTED
    assert order.rejection_reason == "invalid shares"
    assert broker.get_account().cash == 1000.0
    assert broker.get_positions() == []


def test_buy_fill_rejects_insufficient_cash_without_mutation():
    broker = PaperBroker(initial_cash=100.0)
    order = broker.submit_order(_intent("NVDA", OrderSide.BUY, 2, 80.0))

    result = broker.fill_order(order.order_id)

    assert result.ok is False
    assert result.error == "insufficient cash"
    assert broker.get_account().cash == 100.0
    assert broker.get_positions() == []
    assert broker.get_order(order.order_id).filled_quantity == 0


def test_sell_fill_rejects_insufficient_position_without_mutation():
    broker = PaperBroker(initial_cash=1000.0, positions={"AAPL": 1})
    order = broker.submit_order(_intent("AAPL", OrderSide.SELL, 2, 100.0))

    result = broker.fill_order(order.order_id)

    assert result.ok is False
    assert result.error == "insufficient position"
    assert broker.get_account().cash == 1000.0
    assert broker.positions["AAPL"] == 1
    assert broker.get_order(order.order_id).filled_quantity == 0


def test_cancel_open_order_and_reject_future_fills():
    broker = PaperBroker(initial_cash=1000.0)
    order = broker.submit_order(_intent("AAPL", OrderSide.BUY, 2, 100.0))

    cancel = broker.cancel_order(order.order_id)
    fill = broker.fill_order(order.order_id)

    assert cancel.cancelled is True
    assert cancel.order.status == BrokerOrderStatus.CANCELLED
    assert fill.ok is False
    assert "terminal" in fill.error


def test_cancel_terminal_order_is_not_applied():
    broker = PaperBroker(initial_cash=1000.0)
    order = broker.submit_order(_intent("AAPL", OrderSide.BUY, 1, 100.0))
    broker.fill_order(order.order_id)

    cancel = broker.cancel_order(order.order_id)

    assert cancel.cancelled is False
    assert cancel.order.status == BrokerOrderStatus.FILLED
    assert "terminal" in cancel.reason


def test_order_store_lists_by_status_and_symbol():
    store = InMemoryOrderStore()
    broker = PaperBroker(initial_cash=1000.0, order_store=store)
    aapl = broker.submit_order(_intent("AAPL", OrderSide.BUY, 1, 100.0))
    msft = broker.submit_order(_intent("MSFT", OrderSide.BUY, 1, 100.0))
    broker.fill_order(aapl.order_id)

    assert [order.order_id for order in store.list(symbol="MSFT")] == [msft.order_id]
    assert [order.order_id for order in store.list(status=BrokerOrderStatus.FILLED)] == [aapl.order_id]
    assert [order.order_id for order in store.open_orders()] == [msft.order_id]
    with pytest.raises(ValueError):
        store.create(msft)


def test_quotes_account_snapshot_and_reconciliation_success():
    broker = PaperBroker(initial_cash=700.0, positions={"AAPL": 3})
    broker.set_quote("AAPL", Quote(symbol="AAPL", price=100.0))

    account = broker.get_account()
    positions = broker.get_positions()
    quotes = broker.get_quotes(["AAPL", "MSFT"])
    report = reconcile_account(
        expected_cash=700.0,
        expected_positions={"AAPL": 3},
        account=account,
        positions=positions,
    )

    assert account.total_value == 1000.0
    assert quotes["AAPL"].price == 100.0
    assert report.ok is True
    assert report.differences == ()


def test_reconciliation_reports_cash_and_position_differences():
    broker = PaperBroker(initial_cash=700.0, positions={"AAPL": 3})

    report = reconcile_account(
        expected_cash=800.0,
        expected_positions={"AAPL": 2, "MSFT": 1},
        account=broker.get_account(),
        positions=broker.get_positions(),
    )

    assert report.ok is False
    assert {(diff.kind, diff.symbol) for diff in report.differences} == {
        ("cash", None),
        ("position", "AAPL"),
        ("position", "MSFT"),
    }


def _intent(symbol: str, side: OrderSide, shares: int, price: float) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,
        shares=shares,
        limit_price=price,
        source_action=side.value,
        source_justification="test",
    )
