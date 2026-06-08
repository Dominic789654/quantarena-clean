"""Tests for shared execution helpers."""

from backtest.execution import (
    convert_targets_to_trades,
    execute_buy_order,
    execute_sell_order,
    record_portfolio_snapshot,
)


def test_execute_buy_order_updates_portfolio_and_records_trade():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 2, "value": 20.0}},
    }
    recorded = []
    warnings = []

    applied = execute_buy_order(
        current_portfolio=portfolio,
        date="2026-01-02",
        ticker="AAA",
        shares=3,
        price=10.0,
        record_trade=lambda *args: recorded.append(args),
        warn=warnings.append,
    )

    assert applied is True
    assert portfolio["cashflow"] == 970.0
    assert portfolio["positions"]["AAA"] == {"shares": 5, "value": 50.0}
    assert recorded == [("2026-01-02", "AAA", "BUY", 3, 10.0)]
    assert warnings == []


def test_execute_buy_order_rejects_insufficient_cash():
    portfolio = {
        "cashflow": 5.0,
        "positions": {"AAA": {"shares": 2, "value": 20.0}},
    }
    recorded = []
    warnings = []

    applied = execute_buy_order(
        current_portfolio=portfolio,
        date="2026-01-02",
        ticker="AAA",
        shares=1,
        price=10.0,
        record_trade=lambda *args: recorded.append(args),
        warn=warnings.append,
    )

    assert applied is False
    assert portfolio["cashflow"] == 5.0
    assert portfolio["positions"]["AAA"] == {"shares": 2, "value": 20.0}
    assert recorded == []
    assert warnings == ["Insufficient cash for AAA buy"]


def test_execute_sell_order_updates_portfolio_and_records_trade():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 5, "value": 50.0}},
    }
    recorded = []
    warnings = []

    applied = execute_sell_order(
        current_portfolio=portfolio,
        date="2026-01-02",
        ticker="AAA",
        shares=3,
        price=10.0,
        record_trade=lambda *args: recorded.append(args),
        warn=warnings.append,
    )

    assert applied is True
    assert portfolio["cashflow"] == 1030.0
    assert portfolio["positions"]["AAA"] == {"shares": 2, "value": 20.0}
    assert recorded == [("2026-01-02", "AAA", "SELL", 3, 10.0)]
    assert warnings == []


def test_execute_sell_order_clamps_to_current_holding():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 2, "value": 20.0}},
    }
    recorded = []
    warnings = []

    applied = execute_sell_order(
        current_portfolio=portfolio,
        date="2026-01-02",
        ticker="AAA",
        shares=5,
        price=10.0,
        record_trade=lambda *args: recorded.append(args),
        warn=warnings.append,
    )

    assert applied is True
    assert portfolio["cashflow"] == 1020.0
    assert portfolio["positions"]["AAA"] == {"shares": 0, "value": 0.0}
    assert recorded == [("2026-01-02", "AAA", "SELL", 2, 10.0)]
    assert warnings == ["Insufficient shares for AAA sell"]


def test_execute_sell_order_returns_false_when_no_shares_after_clamp():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 0, "value": 0.0}},
    }
    recorded = []
    warnings = []

    applied = execute_sell_order(
        current_portfolio=portfolio,
        date="2026-01-02",
        ticker="AAA",
        shares=5,
        price=10.0,
        record_trade=lambda *args: recorded.append(args),
        warn=warnings.append,
    )

    assert applied is False
    assert portfolio["cashflow"] == 1000.0
    assert recorded == []
    assert warnings == ["Insufficient shares for AAA sell"]


def test_execute_buy_order_rejects_invalid_price_with_risk_warning():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 0, "value": 0.0}},
    }
    recorded = []
    warnings = []

    applied = execute_buy_order(
        current_portfolio=portfolio,
        date="2026-01-02",
        ticker="AAA",
        shares=1,
        price=0.0,
        record_trade=lambda *args: recorded.append(args),
        warn=warnings.append,
    )

    assert applied is False
    assert recorded == []
    assert warnings == ["Risk gate rejected AAA buy: invalid_price"]


def test_execute_sell_order_rejects_invalid_price_with_risk_warning():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 2, "value": 20.0}},
    }
    recorded = []
    warnings = []

    applied = execute_sell_order(
        current_portfolio=portfolio,
        date="2026-01-02",
        ticker="AAA",
        shares=1,
        price=0.0,
        record_trade=lambda *args: recorded.append(args),
        warn=warnings.append,
    )

    assert applied is False
    assert portfolio["positions"]["AAA"] == {"shares": 2, "value": 20.0}
    assert recorded == []
    assert warnings == ["Risk gate rejected AAA sell: invalid_price"]


def test_record_portfolio_snapshot_updates_marked_values_and_records_snapshot():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {
            "AAA": {"shares": 2, "value": 0.0},
            "BBB": {"shares": 3, "value": 123.0},
        },
    }
    prices = {"AAA": 10.125}
    recorded = []

    record_portfolio_snapshot(
        current_portfolio=portfolio,
        date="2026-01-02",
        prices=prices,
        record_snapshot=lambda *args: recorded.append(args),
    )

    assert portfolio["positions"]["AAA"] == {"shares": 2, "value": 20.25}
    assert portfolio["positions"]["BBB"] == {"shares": 3, "value": 123.0}
    assert recorded == [
        (
            "2026-01-02",
            1000.0,
            portfolio["positions"],
            prices,
        )
    ]
    assert recorded[0][2] is not portfolio["positions"]


def test_convert_targets_to_trades_applies_buy_and_records_trade():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 0, "value": 0.0}},
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 0.5},
        prices={"AAA": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"]["action"] == "BUY"
    assert decisions["AAA"]["shares"] == 50
    assert decisions["AAA"]["_applied"] is True
    assert portfolio["cashflow"] == 500.0
    assert portfolio["positions"]["AAA"] == {"shares": 50, "value": 500.0}
    assert recorded == [
        (
            "2026-01-02",
            "AAA",
            "BUY",
            50,
            10.0,
            "Target allocation: 50.0% (current: 0 shares)",
        )
    ]


def test_convert_targets_to_trades_applies_sell_and_records_trade():
    portfolio = {
        "cashflow": 100.0,
        "positions": {"AAA": {"shares": 50, "value": 500.0}},
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 0.2},
        prices={"AAA": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"]["action"] == "SELL"
    assert decisions["AAA"]["shares"] == 38
    assert decisions["AAA"]["_applied"] is True
    assert portfolio["cashflow"] == 480.0
    assert portfolio["positions"]["AAA"] == {"shares": 12, "value": 120.0}
    assert recorded == [
        (
            "2026-01-02",
            "AAA",
            "SELL",
            38,
            10.0,
            "Target allocation: 20.0% (current: 50 shares)",
        )
    ]


def test_convert_targets_to_trades_clamps_buy_to_available_cash():
    portfolio = {
        "cashflow": 25.0,
        "positions": {
            "AAA": {"shares": 0, "value": 0.0},
            "BBB": {"shares": 10, "value": 100.0},
        },
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 0.5},
        prices={"AAA": 10.0, "BBB": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"]["action"] == "BUY"
    assert decisions["AAA"]["shares"] == 2
    assert decisions["AAA"]["_risk_reasons"] == ["cash_limit"]
    assert portfolio["cashflow"] == 5.0
    assert portfolio["positions"]["AAA"] == {"shares": 2, "value": 20.0}
    assert recorded[0][:5] == ("2026-01-02", "AAA", "BUY", 2, 10.0)


def test_convert_targets_to_trades_clamps_sell_to_current_holding():
    portfolio = {
        "cashflow": 0.0,
        "positions": {"AAA": {"shares": 5, "value": 50.0}},
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": -0.5},
        prices={"AAA": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"]["action"] == "SELL"
    assert decisions["AAA"]["shares"] == 5
    assert portfolio["cashflow"] == 50.0
    assert portfolio["positions"]["AAA"] == {"shares": 0, "value": 0.0}
    assert recorded[0][:5] == ("2026-01-02", "AAA", "SELL", 5, 10.0)


def test_convert_targets_to_trades_liquidates_zero_target_weight():
    portfolio = {
        "cashflow": 0.0,
        "positions": {"AAA": {"shares": 5, "value": 50.0}},
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 0.0},
        prices={"AAA": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"]["action"] == "SELL"
    assert decisions["AAA"]["shares"] == 5
    assert portfolio["cashflow"] == 50.0
    assert portfolio["positions"]["AAA"] == {"shares": 0, "value": 0.0}
    assert recorded[0][:5] == ("2026-01-02", "AAA", "SELL", 5, 10.0)


def test_convert_targets_to_trades_holds_when_target_already_met():
    portfolio = {
        "cashflow": 500.0,
        "positions": {"AAA": {"shares": 50, "value": 500.0}},
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 0.5},
        prices={"AAA": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"] == {
        "action": "HOLD",
        "shares": 0,
        "justification": "Target allocation 50.0% achieved",
        "_applied": True,
    }
    assert portfolio["cashflow"] == 500.0
    assert recorded == []


def test_convert_targets_to_trades_holds_when_cash_is_insufficient():
    portfolio = {
        "cashflow": 5.0,
        "positions": {
            "AAA": {"shares": 0, "value": 0.0},
            "BBB": {"shares": 10, "value": 100.0},
        },
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 1.0},
        prices={"AAA": 10.0, "BBB": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"] == {
        "action": "HOLD",
        "shares": 0,
        "justification": "Insufficient cash for target allocation",
        "_applied": True,
        "_risk_reasons": ["cash_limit"],
    }
    assert recorded == []


def test_convert_targets_to_trades_holds_when_price_is_zero_and_no_position():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 0, "value": 0.0}},
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 1.0},
        prices={"AAA": 0.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"] == {
        "action": "HOLD",
        "shares": 0,
        "justification": "Target allocation 100.0% achieved",
        "_applied": True,
    }
    assert recorded == []


def test_convert_targets_to_trades_rejects_zero_price_liquidation():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 5, "value": 0.0}},
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 1.0},
        prices={"AAA": 0.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"] == {
        "action": "HOLD",
        "shares": 0,
        "justification": "Invalid price for target allocation",
        "_applied": True,
        "_risk_reasons": ["invalid_price"],
    }
    assert portfolio["cashflow"] == 1000.0
    assert portfolio["positions"]["AAA"] == {"shares": 5, "value": 0.0}
    assert recorded == []


def test_convert_targets_to_trades_uses_sequential_cash_for_multiple_buys():
    portfolio = {
        "cashflow": 100.0,
        "positions": {
            "AAA": {"shares": 0, "value": 0.0},
            "BBB": {"shares": 0, "value": 0.0},
        },
    }
    recorded = []

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 1.0, "BBB": 1.0},
        prices={"AAA": 10.0, "BBB": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: recorded.append(args),
    )

    assert decisions["AAA"]["action"] == "BUY"
    assert decisions["AAA"]["shares"] == 10
    assert decisions["BBB"] == {
        "action": "HOLD",
        "shares": 0,
        "justification": "Insufficient cash for target allocation",
        "_applied": True,
        "_risk_reasons": ["cash_limit"],
    }
    assert portfolio["cashflow"] == 0.0
    assert portfolio["positions"]["AAA"] == {"shares": 10, "value": 100.0}
    assert recorded == [
        (
            "2026-01-02",
            "AAA",
            "BUY",
            10,
            10.0,
            "Target allocation: 100.0% (current: 0 shares)",
        )
    ]


def test_convert_targets_to_trades_skips_tickers_without_prices():
    portfolio = {
        "cashflow": 1000.0,
        "positions": {"AAA": {"shares": 0, "value": 0.0}},
    }

    decisions = convert_targets_to_trades(
        current_portfolio=portfolio,
        target_positions={"AAA": 0.5, "BBB": 0.5},
        prices={"AAA": 10.0},
        date="2026-01-02",
        record_trade=lambda *args: None,
    )

    assert set(decisions) == {"AAA"}
