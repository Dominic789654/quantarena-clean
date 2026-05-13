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

from backtest.data_loader import DataPrefetcher
from backtest.portfolio_tracker import PortfolioTracker, DailySnapshot, Trade
from backtest.metrics import PerformanceMetrics
from backtest.report import ReportGenerator
from backtest.engine import BacktestEngine, BacktestResult, create_backtest_engine, run_backtest
from backtest.fof_allocator import FOFAllocationResult, FOFAllocator, SleeveSnapshot
from backtest.workflow_adapter import BacktestWorkflowAdapter, BacktestDecision, create_workflow_adapter

__all__ = [
    "DataPrefetcher",
    "PortfolioTracker",
    "DailySnapshot",
    "Trade",
    "PerformanceMetrics",
    "ReportGenerator",
    "BacktestEngine",
    "BacktestResult",
    "create_backtest_engine",
    "run_backtest",
    "FOFAllocator",
    "FOFAllocationResult",
    "SleeveSnapshot",
    "BacktestWorkflowAdapter",
    "BacktestDecision",
    "create_workflow_adapter",
]

# Optional: Portfolio allocator / FOF engine / multi-personality extras
try:
    from backtest.portfolio_allocator import PortfolioAllocator
    from backtest.fof_engine import FOFBacktestEngine
    from backtest.multi_personality_engine import (
        MultiPersonalityBacktest,
        MultiPersonalityComparison,
        PersonalityResult,
        SharedDataCache,
        run_multi_personality_backtest,
    )

    __all__ += [
        "PortfolioAllocator",
        "FOFBacktestEngine",
        "MultiPersonalityBacktest",
        "MultiPersonalityComparison",
        "PersonalityResult",
        "SharedDataCache",
        "run_multi_personality_backtest",
    ]
except ImportError:
    pass
