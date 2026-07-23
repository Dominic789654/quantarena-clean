"""BacktestDecision: container for a trading decision from the workflow.

Moved verbatim (behavior-preserving) from backtest/workflow_adapter.py
by the extract-workflow-pure-dataclasses-and-caches change
(docs/refactor_program_plan.md Phase 3). backtest/workflow_adapter.py
re-imports this name so every existing `from backtest.workflow_adapter
import BacktestDecision` import keeps resolving.
"""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class BacktestDecision:
    """Container for a trading decision from the workflow."""
    ticker: str
    action: str  # "BUY", "SELL", "HOLD"
    shares: int
    price: float
    justification: str
    analyst_signals: Dict[str, Any]  # Raw analyst signals for reporting
