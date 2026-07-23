"""backtest.workflow: decomposed pieces of backtest/workflow_adapter.py.

Extraction target for the Phase 3 decomposition program
(docs/refactor_program_plan.md Phase 3). `backtest/workflow_adapter.py`
re-imports every name below so existing `from backtest.workflow_adapter
import <Name>` imports and monkeypatch string paths keep resolving
while the implementations live here.
"""
