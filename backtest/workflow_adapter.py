"""
Backtest Workflow Adapter (compatibility shim)
===============================================

This module used to contain `BacktestWorkflowAdapter` and
`create_workflow_adapter` directly. Both now live in
`backtest/workflow/adapter.py` (see docs/refactor_program_plan.md
Phase 3, step 22 — the finale of the workflow_adapter decomposition
program; every other piece was already extracted into
`backtest/workflow/` by earlier Phase 3 steps).

This module is now purely a compatibility surface: it re-exports every
name that used to be importable from here, so every existing
`from backtest.workflow_adapter import <Name>` import,
`backtest/__init__.py`'s lazy `_EXPORTS` table, and every
`monkeypatch.setattr("backtest.workflow_adapter.<Name>...", ...)` /
`monkeypatch.setattr("backtest.workflow_adapter.logger.info", ...)`
string path keep resolving against the same objects. `logger` is kept
as a bare re-export (not just reachable transitively) specifically for
the `logger.info` monkeypatch: `loguru.logger` is a process-wide
singleton, so this module's `from loguru import logger` and
`backtest/workflow/adapter.py`'s own `from loguru import logger` bind
the identical object — patching `.info` through either module path has
the identical effect on every `logger.info(...)` call site, wherever
it lives.
"""

from loguru import logger  # noqa: F401

from backtest.workflow.decisions import BacktestDecision  # noqa: F401
from backtest.workflow.phase1_artifact import (  # noqa: F401
    SharedPhase1Artifact,
    SharedPhase1ArtifactCache,
)
from backtest.workflow.signal_cache import SharedAnalystSignalCache  # noqa: F401
from backtest.workflow.adapter import BacktestWorkflowAdapter, create_workflow_adapter  # noqa: F401
