"""`deepear.src.agents.report` -- the decomposed home of `ReportAgent`.

Phase 4 of docs/refactor_program_plan.md split `deepear/src/agents/report_agent.py`
(1660 lines, one `ReportAgent` class) into this package's leaf modules
(`retry.py`, `chart_sanitizer.py`, `structured_report.py`, `citations.py`,
`ticker_utils.py`, `forecast_requests.py`, `chart_renderer.py`, `clustering.py`)
plus `agent.py` (the `ReportAgent` class itself, added by
`finalize-report-agent-package-and-shim`, step 31 -- the finale of the
program). This is now a real package `__init__.py` (not a namespace-package
placeholder): it re-exports `ReportAgent` and each leaf module's public
function, so `from deepear.src.agents.report import ReportAgent,
cluster_signals, ...` works alongside the fully-qualified per-module import
spelling every existing call site and test already uses (both keep
resolving to the same objects; nothing here changes which module a name is
*defined* in).
"""

from deepear.src.agents.report.agent import ReportAgent
from deepear.src.agents.report.retry import run_agent_with_retry
from deepear.src.agents.report.chart_sanitizer import sanitize_json_chart_blocks
from deepear.src.agents.report.structured_report import build_structured_report
from deepear.src.agents.report.citations import (
    make_cite_key,
    build_bibliography,
    render_references_section,
    inject_references,
    normalize_citations,
    clean_markdown,
)
from deepear.src.agents.report.ticker_utils import clean_ticker, signal_mentions_ticker
from deepear.src.agents.report.forecast_requests import extract_forecast_requests, build_forecast_map
from deepear.src.agents.report.chart_renderer import process_charts
from deepear.src.agents.report.clustering import cluster_signals

__all__ = [
    "ReportAgent",
    "run_agent_with_retry",
    "sanitize_json_chart_blocks",
    "build_structured_report",
    "make_cite_key",
    "build_bibliography",
    "render_references_section",
    "inject_references",
    "normalize_citations",
    "clean_markdown",
    "clean_ticker",
    "signal_mentions_ticker",
    "extract_forecast_requests",
    "build_forecast_map",
    "process_charts",
    "cluster_signals",
]
