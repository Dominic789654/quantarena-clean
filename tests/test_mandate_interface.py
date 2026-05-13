"""Tests for the shared mandate allocation interface."""

from dataclasses import dataclass

import pytest

from backtest.mandate_interface import allocate_with_mandate


@dataclass
class _Portfolio:
    cashflow: float
    positions: dict


@dataclass
class _RecordingAllocator:
    result: dict

    def __post_init__(self):
        self.calls = []

    def allocate(self, signals, current_portfolio, prices, trading_date, decision_memory=None):
        self.calls.append(
            {
                "signals": signals,
                "current_portfolio": current_portfolio,
                "prices": prices,
                "trading_date": trading_date,
                "decision_memory": decision_memory,
            }
        )
        return dict(self.result)


def test_allocate_with_mandate_forwards_contract_arguments():
    allocator = _RecordingAllocator(result={"AAA": 0.4})
    portfolio = _Portfolio(cashflow=1000.0, positions={"AAA": 2})
    signals = {"AAA": {"signal": "BULLISH"}}
    prices = {"AAA": 10.0}
    memory = [{"ticker": "AAA", "action": "BUY"}]

    result = allocate_with_mandate(
        allocator,
        signals=signals,
        current_portfolio=portfolio,
        prices=prices,
        trading_date="2024-01-02",
        decision_memory=memory,
    )

    assert result == {"AAA": 0.4}
    assert len(allocator.calls) == 1
    assert allocator.calls[0]["signals"] is signals
    assert allocator.calls[0]["current_portfolio"] is portfolio
    assert allocator.calls[0]["prices"] is prices
    assert allocator.calls[0]["trading_date"] == "2024-01-02"
    assert allocator.calls[0]["decision_memory"] is memory


def test_allocate_with_mandate_uses_none_decision_memory_by_default():
    allocator = _RecordingAllocator(result={})

    allocate_with_mandate(
        allocator,
        signals={},
        current_portfolio=_Portfolio(cashflow=0.0, positions={}),
        prices={},
        trading_date="2024-01-02",
    )

    assert allocator.calls[0]["decision_memory"] is None


def test_allocate_with_mandate_requires_keyword_arguments():
    allocator = _RecordingAllocator(result={})

    with pytest.raises(TypeError):
        allocate_with_mandate(allocator, {}, _Portfolio(cashflow=0.0, positions={}), {}, "2024-01-02")
