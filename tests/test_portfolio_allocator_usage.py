"""Portfolio allocator must record LLM usage on its (only) agno path,
so run manifests don't undercount portfolio-mode spend."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import backtest.portfolio_allocator as allocator_mod
from backtest.portfolio_allocator import Portfolio, PortfolioAllocator


def test_allocate_records_token_usage(monkeypatch):
    allocator = PortfolioAllocator(personality="balanced", llm_provider="deepseek",
                                   llm_model="deepseek-v4-flash")

    fake_agent = Mock()
    fake_agent.run.return_value = SimpleNamespace(content='{"AAA": 0.5, "BBB": 0.5}')

    with patch.object(allocator_mod, "get_model", return_value=Mock()), \
         patch.object(allocator_mod, "Agent", return_value=fake_agent), \
         patch.object(allocator_mod, "record_token_usage") as mock_record:
        monkeypatch.setattr(allocator_mod, "TOKEN_TRACKER_AVAILABLE", True)
        allocations = allocator.allocate(
            signals={"AAA": SimpleNamespace(signal="Bullish", justification="x"),
                     "BBB": SimpleNamespace(signal="Bullish", justification="y")},
            current_portfolio=Portfolio(cashflow=1000.0, positions={}),
            prices={"AAA": 10.0, "BBB": 10.0},
            trading_date="2026-07-23",
        )

    assert allocations  # allocation parsed
    mock_record.assert_called_once()
    args = mock_record.call_args.args
    assert args[0] == "portfolio_allocator"
    assert args[1] >= 1 and args[2] >= 1  # non-zero token estimates
    assert args[3] == "deepseek"
