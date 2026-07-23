"""`deepear.src.agents.report` -- the future home of `ReportAgent`'s decomposed pieces.

Phase 4 of docs/refactor_program_plan.md splits `deepear/src/agents/report_agent.py`
(1660 lines, one `ReportAgent` class) into leaf modules under this package. This
package's `__init__.py` intentionally has no re-exports yet: each leaf module
(starting with `retry.py`, added by `extract-report-agent-retry-helper`) is
imported by its fully-qualified path (`deepear.src.agents.report.retry`, etc.) from
`report_agent.py` and from tests, following the same fully-qualified-import
convention `report_agent.py` itself already uses for its `deepear.src.*` imports
(bare `agents.*` resolves to `deepfund`'s package per
`openspec/changes/archive/2026-07-23-pin-agents-package-resolution/`). Re-exports
can be added here later (e.g. by `finalize-report-agent-package-and-shim`) if a
package-level shim becomes useful.
"""
