"""ReportAgent (compatibility shim)
===================================

This module used to contain the `ReportAgent` class directly (1660 lines,
before Phase 4 of docs/refactor_program_plan.md began decomposing it). By
the finalize-report-agent-package-and-shim change (Phase 4, step 31 -- the
finale of the report_agent decomposition program), `ReportAgent` itself has
moved to `deepear/src/agents/report/agent.py`; every other piece (`retry.py`,
`chart_sanitizer.py`, `structured_report.py`, `citations.py`,
`ticker_utils.py`, `forecast_requests.py`, `chart_renderer.py`,
`clustering.py`) was already extracted into `deepear/src/agents/report/` by
earlier Phase 4 steps.

This module is now purely a compatibility surface: it re-exports
`ReportAgent` so every existing `from deepear.src.agents.report_agent import
ReportAgent` import (and `deepear/src/agents/__init__.py`'s own import of
the same name) keeps resolving to the same class object.

`ReportAgent`'s methods now execute in `deepear.src.agents.report.agent`'s
namespace, not this module's -- so `Agent`, `ForecastAgent`, and the
`_*_impl` delegation targets are no longer meaningfully patchable through
this module (an audit of every test/consumer found none of them referenced
here except through `tests/report_agent_harness.py` and two test files,
which this change updated to patch `deepear.src.agents.report.agent`
directly; see design.md). Re-exporting those names from this shim would not
restore the old patch behavior (the class body would still read the *other*
module's global), so they are intentionally not re-exported here -- only
`ReportAgent` itself, which is genuinely referenced through this module's
import path.
"""

from deepear.src.agents.report.agent import ReportAgent  # noqa: F401

__all__ = ["ReportAgent"]
