## Context

`ReportAgent` (`deepear/src/agents/report_agent.py`) builds a numbered,
anchored bibliography for every generated report: `_build_bibliography`
scans signals for source attributions and produces `(bib_entries,
signal_to_keys)`; the Writer/Editor agents are prompted to cite sources
using either a stable `[@KEY]` marker or a legacy `[[n]]` marker;
`_normalize_citations` rewrites both marker forms (plus a loose
paren-wrapped `（@KEY）`/`(@KEY)` form models sometimes emit instead of the
bracket form) into `[N](#ref-KEY)`; `_render_references_section` renders
`bib_entries` into a `"## 参考文献"` markdown block; and `_inject_references`
either replaces an existing `"## 参考文献"` section in the report or appends
one at the end. `_make_cite_key` is the deterministic hashing function
(`sha1` of the URL, or of `title|source_name` when no URL is available,
truncated to an 8-hex-char `SF-` prefixed key) all of the above key off of.

`grep -n "self\."` restricted to each of the six original method bodies
finds matches in exactly one: `_build_bibliography` reads
`self._make_cite_key(url=..., title=..., source_name=...)` and
`self.db.lookup_reference_by_url(url)`. The other five --
`_make_cite_key`, `_render_references_section`, `_inject_references`,
`_normalize_citations`, `_clean_markdown` -- touch no instance/class state
at all.

`_clean_markdown` is a defined instance method (`def _clean_markdown(self,
text)`) that never reads or writes `self`; it strips a leading ` ```markdown
` or bare ` ``` ` fence and a trailing ` ``` ` fence from LLM responses
during section editing, summary generation, and tail-content generation
(`_incremental_edit`). It is not chart-specific (chart-fence repair already
lives in `chart_sanitizer.py`, extracted in step 26) and it is markdown/
citation-adjacent cleanup glue used throughout the same report-assembly
pipeline this step is extracting, so it satisfies the plan's `ONLY IF`
condition for inclusion here.

`_normalize_citations` has a documented history: the Phase 0 change
`fix-report-agent-citation-normalize-args`
(`openspec/changes/archive/2026-07-23-fix-report-agent-citation-normalize-args/`)
fixed a call site in `generate_report`'s non-incremental branch that had
been calling the method with only two of its three required arguments
(`report_md`, `signal_to_keys`, `key_to_num`), causing a `TypeError` at
final assembly for any `ReportAgent(..., incremental_edit=False)` run under
the 80k-char incremental threshold. `tests/test_report_agent_citations.py`
is the regression test for that fix; it builds a real `ReportAgent` and
drives `generate_report` down the exact fixed branch.

## Goals / Non-Goals

**Goals:** move all six method bodies verbatim into
`deepear/src/agents/report/citations.py`; thread `self.db` through
`build_bibliography` as an explicit required keyword-only `db` parameter
(ground rule 6); keep all six `ReportAgent` attributes as real, correctly-
bound (staticmethod vs. instance method) delegators so every existing
internal call site, every existing class-level `ReportAgent._make_cite_key
(...)` fixture-derivation call, and any future monkeypatch of any of the
six names keeps working; add direct tests for the new module's previously-
uncovered behavior plus delegation-identity tests.

**Non-Goals:** changing cite-key derivation, bibliography construction,
references rendering, injection, or citation-marker normalization behavior
in any way; reintroducing or otherwise touching the fixed
`_normalize_citations` call-site bug; moving `_clean_ticker` /
`_signal_mentions_ticker` (step 28, `extract-report-agent-forecast-and-
ticker-coordinator`) or any chart-rendering code (step 29,
`extract-report-agent-chart-renderer`); building out `deepear/src/agents/
report/__init__.py` re-exports (deferred to `finalize-report-agent-package-
and-shim`, step 31).

## Decisions

1. **`build_bibliography(signals, *, db)`**: the only threaded dependency
   this step introduces. `db` is required and keyword-only, mirroring
   `retry.py`'s `run_agent_with_retry(..., *, max_retries, timeout_seconds,
   retry_delay)` precedent -- a threaded dependency should never silently
   default to something that isn't the caller's own instance state.
   `ReportAgent._build_bibliography(self, signals)` forwards `db=self.db`.
2. **`_build_bibliography`'s `self._make_cite_key(...)` call becomes a
   plain in-module call to `make_cite_key(...)`, not a threaded
   dependency**: unlike `self.db`, `_make_cite_key` is itself moving into
   the same module in this same step, so `build_bibliography` can call
   `make_cite_key(...)` directly without any indirection -- there is no
   `self` left to thread once both functions live together.
3. **All six `ReportAgent` attributes keep their original binding kind**:
   `_make_cite_key`, `_render_references_section`, `_inject_references`,
   `_normalize_citations` stay `@staticmethod`s (matching their original
   decorator) because none of them need instance state even after the
   move. `_build_bibliography` stays a bound instance method because it
   must read `self.db` to forward it. `_clean_markdown` stays a bound
   instance method purely to preserve its existing `self._clean_markdown
   (...)` call spelling at four internal call sites, even though its body
   needs no instance state -- changing it to a staticmethod would be a
   gratuitous binding-kind change ground rule 2 asks to avoid, and would
   break nothing today but adds needless risk for zero benefit.
4. **New test file, not an extension of the characterization suite or
   `test_report_agent_citations.py`**: `tests/test_report_citations_module.py`
   is new, following the `test_report_retry_helper.py` precedent, so the
   characterization suite's charter (pinning `ReportAgent`'s behavior
   ahead of extraction) and the Phase 0 regression test's charter (pinning
   the `_normalize_citations` argument-count fix specifically) both stay
   unchanged in shape.
5. **Coverage gap analysis instead of duplication**: `grep -n "\[\[\|loose"
   tests/test_report_agent_characterization.py tests/test_report_agent_citations.py`
   found no coverage of the legacy `[[n]]` marker or the loose paren-
   wrapped marker forms anywhere in the existing suites (only the `[@KEY]`
   bracket form is exercised, via `test_report_agent_citations.py`'s
   `generate_report` run). The new test file adds direct coverage for
   exactly those two uncovered forms plus `build_bibliography`'s `db`-
   threading (canonical-metadata-wins, missing-lookup-falls-back, and
   cross-signal dedup), none of which any existing test exercises directly.

## Risks / Trade-offs

- Making `db` required and keyword-only in `build_bibliography` means any
  future caller besides `ReportAgent._build_bibliography` must supply it
  explicitly -- acceptable, since the only current caller already has it
  as `self.db` and requiring it explicitly is exactly the point of hoisting
  it out of `self`.
- Including `_clean_markdown` in this step (rather than deferring it) adds
  one more moved name to this step's monkeypatch-audit surface; the audit
  found zero patches of it anywhere, so the risk is limited to keeping its
  binding kind (bound instance method) unchanged, which this design
  explicitly preserves.
