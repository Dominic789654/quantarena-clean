"""Direct tests for the pure functions extracted by
`extract-report-agent-pure-chart-and-structured-report-functions` (Phase 4
step 26, docs/refactor_program_plan.md):
`deepear.src.agents.report.chart_sanitizer.sanitize_json_chart_blocks` and
`deepear.src.agents.report.structured_report.build_structured_report`.

`tests/test_report_agent_characterization.py::TestCleanMarkdownAndSanitize`
already pins three `sanitize_json_chart_blocks`/`_sanitize_json_chart_blocks`
scenarios (well-formed block unchanged, missing-closing-fence repair, no-op
without a `json-chart` marker at all) and one `build_structured_report` shape
assertion buried inside `TestGenerateReportIncrementalHappyPath`. This file
covers the fence-normalization variants and structured-report field mappings
those tests don't exercise, plus a delegation-regression suite proving
`ReportAgent`'s class attributes still produce identical output to the
module-level functions.
"""

from __future__ import annotations

from types import SimpleNamespace

from deepear.src.agents.report.chart_sanitizer import sanitize_json_chart_blocks
from deepear.src.agents.report.structured_report import build_structured_report
from deepear.src.agents.report_agent import ReportAgent
from tests.report_agent_harness import make_report_agent

# ---------------------------------------------------------------------------
# sanitize_json_chart_blocks: fence-variant normalization edge cases
# ---------------------------------------------------------------------------


class TestSanitizeJsonChartBlocksEdgeCases:
    def test_empty_string_is_returned_unchanged(self):
        assert sanitize_json_chart_blocks("") == ""

    def test_json_chart_word_without_any_fence_is_untouched(self):
        # "json-chart" appears in prose (triggers Phase 0's scan) but never as
        # part of a fence, so nothing should be rewritten (aside from Phase
        # 0's `"\n".join` rejoin, which drops the trailing newline -- the
        # same quirk pinned by the characterization suite's well-formed-block
        # test) before the Phase 1 early-return
        # (`"```json-chart" not in text`) fires.
        text = "discussing json-chart format conventions, no fences here.\n"
        assert sanitize_json_chart_blocks(text) == text.rstrip("\n")

    def test_double_backtick_opening_fence_is_normalized_and_repaired(self):
        text = '``json-chart\n{"type": "stock", "ticker": "600001"}\ntrailing text\n'
        repaired = sanitize_json_chart_blocks(text)

        assert "```json-chart" in repaired
        assert "``json-chart" not in repaired.replace("```json-chart", "")
        assert '{"type": "stock", "ticker": "600001"}\n```' in repaired
        assert "trailing text" in repaired

    def test_opening_fence_on_own_line_with_language_on_next_line(self):
        text = '```\njson-chart\n{"type": "stock", "ticker": "600002"}\n```\n'
        repaired = sanitize_json_chart_blocks(text)

        assert repaired.startswith("```json-chart\n")
        assert '{"type": "stock", "ticker": "600002"}' in repaired

    def test_opening_fence_at_end_of_content_line_keeps_prefix(self):
        text = '说明：   ```\njson-chart\n{"type": "stock", "ticker": "600003"}\n```\n'
        repaired = sanitize_json_chart_blocks(text)

        assert repaired.startswith("说明：\n```json-chart\n")
        assert '{"type": "stock", "ticker": "600003"}' in repaired

    def test_double_backtick_closing_fence_is_normalized(self):
        text = '```json-chart\n{"type": "stock", "ticker": "600004"}\n``\n'
        repaired = sanitize_json_chart_blocks(text)

        assert '{"type": "stock", "ticker": "600004"}\n```' in repaired
        assert "``\n" not in repaired.replace("```\n", "")

    def test_closing_fence_on_same_line_as_json_end_preserves_trailing_text(self):
        text = '```json-chart\n{"type": "stock", "ticker": "600005"} ``` after-text\n'
        repaired = sanitize_json_chart_blocks(text)

        assert "after-text" in repaired
        # Phase 0 splits the trailing text onto its own line, outside the fence.
        assert repaired.splitlines()[-1] == "after-text"

    def test_existing_closing_fence_before_next_opening_fence_is_kept_as_is(self):
        # Two well-formed blocks back-to-back: Phase 1's "existing closing
        # fence found before the next opening fence" branch (closing_idx <
        # opening_idx2) should leave both untouched, not insert extras.
        text = (
            '```json-chart\n{"type": "stock", "ticker": "600006"}\n```\n'
            'some prose in between\n'
            '```json-chart\n{"type": "stock", "ticker": "600007"}\n```\n'
        )
        # Phase 0's `"\n".join` rejoin drops the trailing newline.
        assert sanitize_json_chart_blocks(text) == text.rstrip("\n")

    def test_second_of_two_blocks_missing_closing_fence_is_repaired_independently(self):
        text = (
            '```json-chart\n{"type": "stock", "ticker": "600008"}\n```\n'
            '```json-chart\n{"type": "stock", "ticker": "600009"}\n'
            'trailing prose, never closed\n'
        )
        repaired = sanitize_json_chart_blocks(text)

        assert '{"type": "stock", "ticker": "600008"}\n```' in repaired
        assert '{"type": "stock", "ticker": "600009"}\n```' in repaired
        assert "trailing prose, never closed" in repaired

    def test_unterminated_json_object_leaves_remainder_untouched(self):
        # find_json_end returns None (braces never balance) -- Phase 1 keeps
        # the remainder verbatim rather than guessing where to close it.
        text = '```json-chart\n{"type": "stock", "ticker": "600010"\nno closing brace at all\n'
        repaired = sanitize_json_chart_blocks(text)

        # Phase 0's `"\n".join` rejoin drops the trailing newline.
        assert repaired == text.rstrip("\n")


# ---------------------------------------------------------------------------
# build_structured_report: field-mapping coverage
# ---------------------------------------------------------------------------


class TestBuildStructuredReportFieldMapping:
    def test_title_extracted_from_first_h1_line(self):
        report_md = "# My Report Title\n\nsome body text\n"
        result = build_structured_report(report_md, signals=[], clusters=[])
        assert result["title"] == "My Report Title"

    def test_title_defaults_to_placeholder_when_no_h1(self):
        report_md = "## Just a subsection\n\nbody\n"
        result = build_structured_report(report_md, signals=[], clusters=[])
        assert result["title"] == "研报"

    def test_content_before_first_heading_becomes_summary_section(self):
        report_md = "leading paragraph with no heading yet\n## Section A\ncontent A\n"
        result = build_structured_report(report_md, signals=[], clusters=[])

        assert result["sections"][0]["title"] == "摘要"
        assert result["sections"][0]["content"] == "leading paragraph with no heading yet"
        assert result["sections"][1]["title"] == "Section A"
        assert result["sections"][1]["content"] == "content A"

    def test_summary_bullets_extracted_and_capped_at_eight(self):
        bullet_lines = "\n".join(f"- bullet {i}" for i in range(10))
        report_md = f"# T\n{bullet_lines}\n"
        result = build_structured_report(report_md, signals=[], clusters=[])

        assert result["summary_bullets"] == [f"bullet {i}" for i in range(8)]

    def test_summary_bullets_recognizes_all_three_markers(self):
        report_md = "# T\n- dash bullet\n* star bullet\n• dot bullet\nplain line\n"
        result = build_structured_report(report_md, signals=[], clusters=[])

        assert result["summary_bullets"] == ["dash bullet", "star bullet", "dot bullet"]

    def test_dict_signals_are_mapped_with_1_based_ids(self):
        signals = [
            {
                "title": "Sig A",
                "summary": "Summary A",
                "sentiment_score": 0.5,
                "confidence": 0.9,
                "intensity": 3,
                "impact_tickers": ["600001"],
                "expected_horizon": "T+1",
            },
        ]
        result = build_structured_report("# T\n", signals=signals, clusters=[])

        assert result["signals"] == [
            {
                "id": 1,
                "title": "Sig A",
                "summary": "Summary A",
                "sentiment_score": 0.5,
                "confidence": 0.9,
                "intensity": 3,
                "impact_tickers": ["600001"],
                "expected_horizon": "T+1",
            }
        ]

    def test_object_signals_use_attribute_access_fallback(self):
        # Non-dict signals (e.g. Pydantic-model-like objects) go through the
        # `hasattr`/`getattr` branches instead of `.get(...)`.
        signal = SimpleNamespace(
            title="Sig B",
            summary="Summary B",
            sentiment_score=-0.1,
            confidence=0.4,
            intensity=2,
            impact_tickers=[],
            expected_horizon="T+5",
        )
        result = build_structured_report("# T\n", signals=[signal], clusters=[])

        assert result["signals"][0]["title"] == "Sig B"
        assert result["signals"][0]["summary"] == "Summary B"
        assert result["signals"][0]["sentiment_score"] == -0.1

    def test_missing_optional_signal_fields_default_sensibly(self):
        signal = {"title": "Bare signal"}
        result = build_structured_report("# T\n", signals=[signal], clusters=[])

        entry = result["signals"][0]
        assert entry["summary"] == ""
        assert entry["sentiment_score"] is None
        assert entry["confidence"] is None
        assert entry["intensity"] is None
        assert entry["impact_tickers"] == []
        assert entry["expected_horizon"] == ""

    def test_clusters_map_signal_ids_to_full_signal_entries(self):
        signals = [{"title": "First"}, {"title": "Second"}]
        clusters = [{"theme_title": "Theme A", "rationale": "because", "signal_ids": [1, 2]}]
        result = build_structured_report("# T\n", signals=signals, clusters=clusters)

        assert len(result["clusters"]) == 1
        cluster = result["clusters"][0]
        assert cluster["title"] == "Theme A"
        assert cluster["rationale"] == "because"
        assert cluster["signal_ids"] == [1, 2]
        assert [s["title"] for s in cluster["signals"]] == ["First", "Second"]

    def test_cluster_signal_ids_not_in_signal_map_are_dropped(self):
        signals = [{"title": "Only signal"}]
        clusters = [{"theme_title": "Theme A", "signal_ids": [1, 99]}]
        result = build_structured_report("# T\n", signals=signals, clusters=clusters)

        cluster = result["clusters"][0]
        assert cluster["signal_ids"] == [1, 99]
        assert len(cluster["signals"]) == 1
        assert cluster["signals"][0]["title"] == "Only signal"

    def test_clusters_defaulting_when_none_or_empty(self):
        result = build_structured_report("# T\n", signals=[], clusters=None)
        assert result["clusters"] == []

    def test_empty_report_md_yields_default_shape(self):
        result = build_structured_report("", signals=[], clusters=[])

        assert result["title"] == "研报"
        assert result["sections"] == []
        assert result["summary_bullets"] == []
        assert result["signals"] == []
        assert result["clusters"] == []


# ---------------------------------------------------------------------------
# Delegation regression: ReportAgent's class attributes vs. the module
# functions on identical input.
# ---------------------------------------------------------------------------


class TestReportAgentDelegation:
    def test_sanitize_json_chart_blocks_delegator_matches_module_function(self):
        text = (
            '``json-chart\n{"type": "stock", "ticker": "600001"}\ntrailing text\n'
        )
        assert ReportAgent._sanitize_json_chart_blocks(text) == sanitize_json_chart_blocks(text)

    def test_build_structured_report_delegator_matches_module_function(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        report_md = "# Delegated Title\n## Section\ncontent\n- bullet one\n"
        signals = [{"title": "Sig", "summary": "s", "impact_tickers": []}]
        clusters = [{"theme_title": "Theme", "signal_ids": [1]}]

        via_instance = harness.agent.build_structured_report(report_md, signals, clusters)
        via_class = ReportAgent.build_structured_report(report_md, signals, clusters)
        via_module = build_structured_report(report_md, signals, clusters)

        assert via_instance == via_module
        assert via_class == via_module
