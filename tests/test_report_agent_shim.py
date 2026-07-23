"""Shim-integrity tests for `finalize-report-agent-package-and-shim` (Phase 4 step 31).

`ReportAgent` moved from `deepear/src/agents/report_agent.py` into
`deepear/src/agents/report/agent.py`; the old module is now a thin
compatibility shim. These tests pin the contract the shim promises:

- every import spelling that resolved before this change still resolves,
  to the exact same class object (identity, not just equality);
- the shim itself carries no logic -- `ReportAgent` *is* the package class;
- the documented monkeypatch seam is the new module
  (`deepear.src.agents.report.agent`), proven by actually intercepting a
  real `generate_report()` call, not just asserting an attribute exists;
- `deepear.src.agents.report`'s package `__init__.py` re-exports resolve to
  the same objects as their fully-qualified per-module imports.

Note: `from agents.report_agent import ReportAgent` (bare `agents.*`) was
*never* a valid spelling for this class -- `tests/conftest.py`'s
`_pin_ambiguous_package_resolution` fixture pins the bare `agents` package to
`deepfund/src/agents` (the analyst registry), which has no `report_agent`
module at all. Every real call site and test uses the fully-qualified
`deepear.src.agents.report_agent` spelling (see
`openspec/changes/finalize-report-agent-package-and-shim/proposal.md`'s
patch-seam audit), so this file does not test the bare spelling.
"""

from __future__ import annotations

from types import SimpleNamespace

from tests.report_agent_harness import (
    FakeDatabaseManager,
    FakeModel,
    ScriptedAgentRouter,
    make_scripted_agent_class,
)


# ---------------------------------------------------------------------------
# 1. Old import spellings still resolve, to the same object.
# ---------------------------------------------------------------------------


class TestOldImportSpellingsStillWork:
    def test_from_deepear_src_agents_report_agent_import(self):
        from deepear.src.agents.report_agent import ReportAgent
        from deepear.src.agents.report.agent import ReportAgent as RealReportAgent

        assert ReportAgent is RealReportAgent

    def test_module_attribute_access_on_the_shim(self):
        import deepear.src.agents.report_agent as report_agent_shim
        from deepear.src.agents.report.agent import ReportAgent as RealReportAgent

        assert report_agent_shim.ReportAgent is RealReportAgent

    def test_deepear_agents_package_import_still_resolves(self):
        """`deepear/src/agents/__init__.py` imports `ReportAgent` from the
        shim module path; confirm that keeps resolving to the same class.
        """
        import deepear.src.agents as agents_pkg
        from deepear.src.agents.report.agent import ReportAgent as RealReportAgent

        assert agents_pkg.ReportAgent is RealReportAgent

    def test_shim_all_matches_its_re_exports(self):
        import deepear.src.agents.report_agent as report_agent_shim

        assert report_agent_shim.__all__ == ["ReportAgent"]


# ---------------------------------------------------------------------------
# 2. The shim class IS the package class (no wrapping, no logic).
# ---------------------------------------------------------------------------


class TestShimClassIdentity:
    def test_shim_reportagent_is_package_reportagent(self):
        from deepear.src.agents.report_agent import ReportAgent as ShimReportAgent
        from deepear.src.agents.report import ReportAgent as PackageReportAgent

        assert ShimReportAgent is PackageReportAgent

    def test_shim_module_has_no_class_definition_of_its_own(self):
        """The shim must be a pure re-export: `ReportAgent.__module__` names
        the package module, never the shim module."""
        from deepear.src.agents.report_agent import ReportAgent

        assert ReportAgent.__module__ == "deepear.src.agents.report.agent"


# ---------------------------------------------------------------------------
# 3. Patching the NEW namespace intercepts real generate_report internals.
# ---------------------------------------------------------------------------


class TestNewNamespaceIsTheRealSeam:
    def test_patching_report_agent_module_agent_does_not_intercept(self, monkeypatch):
        """Patching the OLD (shim) module's `Agent` attribute (which the
        shim does not even re-export) has no effect on construction --
        proving the shim is not where `ReportAgent`'s methods resolve
        `Agent` from."""
        import deepear.src.agents.report_agent as report_agent_shim

        assert not hasattr(report_agent_shim, "Agent")

    def test_patching_report_dot_agent_module_agent_intercepts_construction(self, monkeypatch):
        import deepear.src.agents.report.agent as report_agent_module
        from deepear.src.agents.report_agent import ReportAgent

        router = ScriptedAgentRouter()
        monkeypatch.setattr(report_agent_module, "Agent", make_scripted_agent_class(router))

        agent = ReportAgent(FakeDatabaseManager(), FakeModel(), incremental_edit=False)

        # All four internal agents are instances of the patched fake class,
        # proving the patch was read from `report.agent`'s own namespace.
        assert agent.planner.__class__.__name__ == "_RoutedFakeAgent"
        assert agent.writer.__class__.__name__ == "_RoutedFakeAgent"
        assert agent.editor.__class__.__name__ == "_RoutedFakeAgent"
        assert agent.section_editor.__class__.__name__ == "_RoutedFakeAgent"

    def test_patching_report_dot_agent_module_agent_intercepts_generate_report(self, monkeypatch):
        """End-to-end: patch `Agent` on the new namespace, run a real
        `generate_report()` call, and confirm the scripted response flows
        all the way through -- proving the seam intercepts actual method
        internals, not just construction."""
        import deepear.src.agents.report.agent as report_agent_module
        from deepear.src.agents.report_agent import ReportAgent

        router = ScriptedAgentRouter()
        router.when_contains("聚类", "not valid json, forces fallback clustering")
        router.when_contains("撰写深度分析章节", "## 章节正文\n\n本节内容。")
        router.when_contains("终稿大纲", "（终稿大纲：保持原有章节顺序，无重大分歧）")
        router.when_contains("生成最终研报", "# 最终研报\n\n正文内容。")
        monkeypatch.setattr(report_agent_module, "Agent", make_scripted_agent_class(router))

        agent = ReportAgent(FakeDatabaseManager(), FakeModel(), incremental_edit=False)
        result = agent.generate_report([{"title": "Signal One"}], user_query="q")

        assert isinstance(result, SimpleNamespace)
        assert "最终研报" in result.content
        # The router recorded calls, proving the FakeAgent (not a real
        # agno.agent.Agent) actually ran.
        assert router.calls


# ---------------------------------------------------------------------------
# 4. `deepear.src.agents.report.__init__` re-exports resolve.
# ---------------------------------------------------------------------------


class TestPackageInitReExports:
    def test_reportagent_reexport(self):
        from deepear.src.agents.report import ReportAgent
        from deepear.src.agents.report.agent import ReportAgent as Direct

        assert ReportAgent is Direct

    def test_leaf_module_function_reexports(self):
        import deepear.src.agents.report as report_pkg
        from deepear.src.agents.report.retry import run_agent_with_retry
        from deepear.src.agents.report.chart_sanitizer import sanitize_json_chart_blocks
        from deepear.src.agents.report.structured_report import build_structured_report
        from deepear.src.agents.report.citations import make_cite_key
        from deepear.src.agents.report.ticker_utils import clean_ticker
        from deepear.src.agents.report.forecast_requests import build_forecast_map
        from deepear.src.agents.report.chart_renderer import process_charts
        from deepear.src.agents.report.clustering import cluster_signals

        assert report_pkg.run_agent_with_retry is run_agent_with_retry
        assert report_pkg.sanitize_json_chart_blocks is sanitize_json_chart_blocks
        assert report_pkg.build_structured_report is build_structured_report
        assert report_pkg.make_cite_key is make_cite_key
        assert report_pkg.clean_ticker is clean_ticker
        assert report_pkg.build_forecast_map is build_forecast_map
        assert report_pkg.process_charts is process_charts
        assert report_pkg.cluster_signals is cluster_signals

    def test_package_all_lists_every_reexport(self):
        import deepear.src.agents.report as report_pkg

        for name in report_pkg.__all__:
            assert hasattr(report_pkg, name), f"{name} listed in __all__ but not an attribute"
