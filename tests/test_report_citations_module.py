"""Tests for `extract-report-agent-citation-manager` (Phase 4 step 27).

Covers the moved module, `deepear.src.agents.report.citations`, directly, plus
the patchability/delegation-identity of the six `ReportAgent` attributes left
behind as one-line delegators (`_make_cite_key`, `_build_bibliography`,
`_render_references_section`, `_inject_references`, `_normalize_citations`,
`_clean_markdown`).

`tests/test_report_agent_citations.py` already pins the Phase 0
`_normalize_citations` two-vs-three-argument bug fix end to end (via a real
`generate_report` run), and
`tests/test_report_agent_characterization.py` already exercises `_make_cite_key`
(class-level calls) and `_clean_markdown` (instance calls) directly. This file
intentionally does not re-derive either of those scenarios; instead it covers:

- `make_cite_key` stability/dedup (same inputs -> same key; URL takes priority
  over title/source when both are present; different inputs -> different keys).
- `build_bibliography` end to end against a small scripted signal list,
  including the `db`-threading this extraction introduced (canonical DB
  metadata wins over signal-provided fields; missing DB lookups fall back to
  signal-provided fields; multiple signals citing the same source dedup to one
  bibliography entry with both signal indices recorded).
- `render_references_section` + `inject_references` round-tripping: rendering
  a bibliography into a "## 参考文献" section and injecting it into a report
  that already has one (replace) and one that doesn't (append).
- `normalize_citations` scenarios NOT already pinned elsewhere: the legacy
  `[[n]]` marker form and the loose `（@KEY）`/`(@KEY)` paren-wrapped marker
  form (the `[@KEY]` bracket form is already pinned by
  `test_report_agent_citations.py`).
- Delegation-identity: each of the six `ReportAgent` attributes produces
  output identical to the corresponding module function given the same
  inputs.
"""

from __future__ import annotations

from deepear.src.agents.report.citations import (
    build_bibliography,
    clean_markdown,
    inject_references,
    make_cite_key,
    normalize_citations,
    render_references_section,
)
from deepear.src.agents.report_agent import ReportAgent
from tests.report_agent_harness import FakeDatabaseManager, make_report_agent

# ---------------------------------------------------------------------------
# make_cite_key
# ---------------------------------------------------------------------------


class TestMakeCiteKey:
    def test_same_inputs_produce_the_same_key(self):
        key_a = make_cite_key(url="https://example.com/a", title="Title A", source_name="WireA")
        key_b = make_cite_key(url="https://example.com/a", title="Title A", source_name="WireA")

        assert key_a == key_b
        assert key_a.startswith("SF-")

    def test_different_urls_produce_different_keys(self):
        key_a = make_cite_key(url="https://example.com/a")
        key_b = make_cite_key(url="https://example.com/b")

        assert key_a != key_b

    def test_url_alone_determines_the_key_ignoring_title_and_source(self):
        # The basis is `url` if non-empty, regardless of title/source_name.
        key_with_extra = make_cite_key(url="https://example.com/a", title="Different Title", source_name="DifferentWire")
        key_url_only = make_cite_key(url="https://example.com/a")

        assert key_with_extra == key_url_only

    def test_no_url_falls_back_to_title_and_source_basis(self):
        key_a = make_cite_key(url="", title="Same Title", source_name="Same Wire")
        key_b = make_cite_key(url="", title="Same Title", source_name="Same Wire")
        key_c = make_cite_key(url="", title="Different Title", source_name="Same Wire")

        assert key_a == key_b
        assert key_a != key_c


# ---------------------------------------------------------------------------
# build_bibliography
# ---------------------------------------------------------------------------


class TestBuildBibliography:
    def test_dedups_shared_source_across_two_signals(self):
        shared_source = {
            "title": "Shared Headline",
            "url": "https://example.com/shared",
            "source_name": "SharedWire",
            "publish_time": "2026-07-20",
        }
        signals = [
            {"title": "Signal One", "sources": [shared_source]},
            {"title": "Signal Two", "sources": [shared_source]},
        ]
        db = FakeDatabaseManager()

        bib_entries, signal_to_keys = build_bibliography(signals, db=db)

        assert len(bib_entries) == 1
        key = bib_entries[0]["key"]
        assert signal_to_keys == {1: [key], 2: [key]}

    def test_db_lookup_supplies_canonical_metadata_over_signal_fields(self):
        source = {
            "title": "Stale Title",
            "url": "https://example.com/enriched",
            "source_name": "StaleWire",
            "publish_time": "2026-01-01",
        }
        signals = [{"title": "Signal One", "sources": [source]}]
        db = FakeDatabaseManager(
            references={
                "https://example.com/enriched": {
                    "url": "https://example.com/enriched",
                    "title": "Canonical Title",
                    "source": "CanonicalWire",
                    "publish_time": "2026-07-22",
                }
            }
        )

        bib_entries, _ = build_bibliography(signals, db=db)

        assert bib_entries[0]["title"] == "Canonical Title"
        assert bib_entries[0]["source"] == "CanonicalWire"
        assert bib_entries[0]["publish_time"] == "2026-07-22"

    def test_missing_db_lookup_falls_back_to_signal_provided_fields(self):
        source = {
            "title": "Only Known Title",
            "url": "https://example.com/unknown",
            "source_name": "OnlyKnownWire",
            "publish_time": "2026-07-20",
        }
        signals = [{"title": "Signal One", "sources": [source]}]
        db = FakeDatabaseManager()  # no references registered -> lookup returns None

        bib_entries, _ = build_bibliography(signals, db=db)

        assert bib_entries[0]["title"] == "Only Known Title"
        assert bib_entries[0]["source"] == "OnlyKnownWire"

    def test_signal_with_no_sources_url_or_title_is_skipped(self):
        # A dict signal with none of `sources`/`url`/`title` set has no
        # source_items at all, so it contributes nothing to the
        # bibliography (the third dict branch in build_bibliography only
        # fires when `url` or `title` is present).
        signals = [{"summary": "No usable citation fields here"}]
        db = FakeDatabaseManager()

        bib_entries, signal_to_keys = build_bibliography(signals, db=db)

        assert bib_entries == []
        assert signal_to_keys == {}

    def test_raw_dict_signal_without_sources_key_is_treated_as_single_source(self):
        # A bare dict signal with url/title but no nested "sources" list is
        # still treated as a single-source entry (the third branch in
        # build_bibliography).
        signals = [
            {
                "title": "Raw Signal Title",
                "url": "https://example.com/raw",
                "source": "RawWire",
                "publish_time": "2026-07-19",
            }
        ]
        db = FakeDatabaseManager()

        bib_entries, signal_to_keys = build_bibliography(signals, db=db)

        assert len(bib_entries) == 1
        assert bib_entries[0]["title"] == "Raw Signal Title"
        assert signal_to_keys == {1: [bib_entries[0]["key"]]}


# ---------------------------------------------------------------------------
# render_references_section + inject_references round-trip
# ---------------------------------------------------------------------------


class TestReferencesRenderAndInjectRoundTrip:
    def _bib_and_map(self):
        bib_entries = [
            {"key": "SF-aaaaaaaa", "url": "https://example.com/a", "title": "Title A", "source": "WireA", "publish_time": "2026-07-20"},
            {"key": "SF-bbbbbbbb", "url": "https://example.com/b", "title": "Title B", "source": "WireB", "publish_time": ""},
        ]
        key_to_num = {"SF-aaaaaaaa": 1, "SF-bbbbbbbb": 2}
        return bib_entries, key_to_num

    def test_render_empty_bibliography(self):
        rendered = render_references_section([], {})

        assert "## 参考文献" in rendered
        assert "（无）" in rendered

    def test_render_includes_anchors_numbers_and_url(self):
        bib_entries, key_to_num = self._bib_and_map()

        rendered = render_references_section(bib_entries, key_to_num)

        assert '<a id="ref-SF-aaaaaaaa"></a>[1] Title A (WireA，2026-07-20), https://example.com/a' in rendered
        # No publish_time -> no "，" suffix; no url -> no trailing ", url".
        assert '<a id="ref-SF-bbbbbbbb"></a>[2] Title B (WireB), https://example.com/b' in rendered

    def test_inject_appends_when_no_existing_section(self):
        report_md = "# Title\n\nBody text.\n"
        bib_entries, key_to_num = self._bib_and_map()
        references_md = render_references_section(bib_entries, key_to_num)

        result = inject_references(report_md, references_md)

        assert result.startswith("# Title\n\nBody text.")
        assert "## 参考文献" in result
        assert result.count("## 参考文献") == 1

    def test_inject_replaces_existing_section_in_place(self):
        report_md = (
            "# Title\n\n"
            "## 参考文献\n\n（占位，将被替换）\n\n"
            "## 风险提示\n\n本报告仅供参考。\n"
        )
        bib_entries, key_to_num = self._bib_and_map()
        references_md = render_references_section(bib_entries, key_to_num)

        result = inject_references(report_md, references_md)

        assert result.count("## 参考文献") == 1
        assert "（占位，将被替换）" not in result
        assert "Title A" in result
        # The section that came after the old references section survives.
        assert "## 风险提示" in result
        assert "本报告仅供参考。" in result


# ---------------------------------------------------------------------------
# normalize_citations: legacy [[n]] and loose paren-wrapped markers
# (the [@KEY] bracket form is already pinned by test_report_agent_citations.py)
# ---------------------------------------------------------------------------


class TestNormalizeCitationsUncoveredMarkerForms:
    def test_legacy_double_bracket_marker_uses_first_key_for_that_signal(self):
        text = "核心判断依据信号支撑 [[1]]。"
        signal_to_keys = {1: ["SF-aaaaaaaa", "SF-cccccccc"]}
        key_to_num = {"SF-aaaaaaaa": 1, "SF-cccccccc": 2}

        result = normalize_citations(text, signal_to_keys, key_to_num)

        assert "[[1]]" not in result
        assert "[1](#ref-SF-aaaaaaaa)" in result

    def test_legacy_marker_with_no_keys_for_signal_is_left_unchanged(self):
        text = "无来源信号 [[9]]。"

        result = normalize_citations(text, signal_to_keys={}, key_to_num={})

        assert result == text

    def test_loose_parenthesized_marker_is_normalized_both_ascii_and_fullwidth(self):
        text = "参考 (@SF-aaaaaaaa) 以及 （@SF-bbbbbbbb）。"
        key_to_num = {"SF-aaaaaaaa": 1, "SF-bbbbbbbb": 2}

        result = normalize_citations(text, signal_to_keys={}, key_to_num=key_to_num)

        assert "(@SF-aaaaaaaa)" not in result
        assert "（@SF-bbbbbbbb）" not in result
        assert "([1](#ref-SF-aaaaaaaa))" in result
        assert "（[2](#ref-SF-bbbbbbbb)）" in result

    def test_unknown_key_renders_placeholder_number(self):
        text = "[@SF-deadbeef]"

        result = normalize_citations(text, signal_to_keys={}, key_to_num={})

        assert result == "[?](#ref-SF-deadbeef)"


# ---------------------------------------------------------------------------
# clean_markdown (module function itself, beyond the fence-stripping already
# pinned via ReportAgent._clean_markdown in test_report_agent_characterization.py)
# ---------------------------------------------------------------------------


class TestCleanMarkdownModuleFunction:
    def test_strips_leading_and_trailing_whitespace_with_no_fence(self):
        assert clean_markdown("  plain content  ") == "plain content"


# ---------------------------------------------------------------------------
# Delegation identity: every ReportAgent attribute this step moved must
# produce output identical to the corresponding module function.
# ---------------------------------------------------------------------------


class TestDelegationIdentity:
    def test_make_cite_key_delegator_matches_module_function(self):
        assert ReportAgent._make_cite_key(url="https://example.com/x", title="T", source_name="S") == make_cite_key(
            url="https://example.com/x", title="T", source_name="S"
        )

    def test_render_references_section_delegator_matches_module_function(self):
        bib_entries = [{"key": "SF-11111111", "url": "https://example.com/x", "title": "T", "source": "S", "publish_time": "2026-07-20"}]
        key_to_num = {"SF-11111111": 1}

        assert ReportAgent._render_references_section(bib_entries, key_to_num) == render_references_section(bib_entries, key_to_num)

    def test_inject_references_delegator_matches_module_function(self):
        report_md = "# Title\n\nBody.\n"
        references_md = "## 参考文献\n\n（无）\n"

        assert ReportAgent._inject_references(report_md, references_md) == inject_references(report_md, references_md)

    def test_normalize_citations_delegator_matches_module_function(self):
        report_md = "核心判断依据信号支撑 [@SF-11111111]。"
        signal_to_keys = {1: ["SF-11111111"]}
        key_to_num = {"SF-11111111": 1}

        assert ReportAgent._normalize_citations(report_md, signal_to_keys, key_to_num) == normalize_citations(
            report_md, signal_to_keys, key_to_num
        )

    def test_build_bibliography_delegator_matches_module_function_given_same_db(self, monkeypatch):
        # _build_bibliography is an instance method (it threads self.db), so
        # the delegation-identity check needs a real ReportAgent instance
        # wired with the same FakeDatabaseManager passed directly to the
        # module function.
        harness = make_report_agent(monkeypatch)
        signals = [
            {
                "title": "Signal One",
                "sources": [
                    {
                        "title": "Source One",
                        "url": "https://example.com/one",
                        "source_name": "WireOne",
                        "publish_time": "2026-07-20",
                    }
                ],
            }
        ]

        via_delegator = harness.agent._build_bibliography(signals)
        via_module = build_bibliography(signals, db=harness.db)

        assert via_delegator == via_module

    def test_clean_markdown_delegator_matches_module_function(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        text = "```markdown\n# Title\n\ncontent\n```"

        assert harness.agent._clean_markdown(text) == clean_markdown(text)
