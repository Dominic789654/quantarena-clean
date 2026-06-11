"""
Backtesting Framework for Unified Agent Trading System
======================================================

Provides historical simulation capabilities for evaluating trading strategies.

Key Components:
- DataPrefetcher: Batch data fetching with caching
- BacktestEngine: Core orchestration for sequential simulation
- PortfolioTracker: Portfolio state management
- PerformanceMetrics: Performance calculations (return, drawdown, Sharpe)
- ReportGenerator: Report and chart generation
- BacktestWorkflowAdapter: DeepFund AgentWorkflow integration for intelligent decisions
- PortfolioAllocator: Multi-stock portfolio allocation (B1 scheme)
- MultiPersonalityBacktest: Parallel multi-personality backtesting (NEW)
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "DataPrefetcher": ("backtest.data_loader", "DataPrefetcher"),
    "PortfolioTracker": ("backtest.portfolio_tracker", "PortfolioTracker"),
    "DailySnapshot": ("backtest.portfolio_tracker", "DailySnapshot"),
    "Trade": ("backtest.portfolio_tracker", "Trade"),
    "PerformanceMetrics": ("backtest.metrics", "PerformanceMetrics"),
    "ReportGenerator": ("backtest.report", "ReportGenerator"),
    "BacktestEngine": ("backtest.engine", "BacktestEngine"),
    "BacktestResult": ("backtest.engine", "BacktestResult"),
    "create_backtest_engine": ("backtest.engine", "create_backtest_engine"),
    "run_backtest": ("backtest.engine", "run_backtest"),
    "FOFAllocator": ("backtest.fof_allocator", "FOFAllocator"),
    "FOFAllocationResult": ("backtest.fof_allocator", "FOFAllocationResult"),
    "SleeveSnapshot": ("backtest.fof_allocator", "SleeveSnapshot"),
    "BacktestWorkflowAdapter": ("backtest.workflow_adapter", "BacktestWorkflowAdapter"),
    "BacktestDecision": ("backtest.workflow_adapter", "BacktestDecision"),
    "create_workflow_adapter": ("backtest.workflow_adapter", "create_workflow_adapter"),
    "PortfolioAllocator": ("backtest.portfolio_allocator", "PortfolioAllocator"),
    "FOFBacktestEngine": ("backtest.fof_engine", "FOFBacktestEngine"),
    "MultiPersonalityBacktest": ("backtest.multi_personality_engine", "MultiPersonalityBacktest"),
    "MultiPersonalityComparison": ("backtest.multi_personality_engine", "MultiPersonalityComparison"),
    "PersonalityResult": ("backtest.multi_personality_engine", "PersonalityResult"),
    "SharedDataCache": ("backtest.multi_personality_engine", "SharedDataCache"),
    "run_multi_personality_backtest": (
        "backtest.multi_personality_engine",
        "run_multi_personality_backtest",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
