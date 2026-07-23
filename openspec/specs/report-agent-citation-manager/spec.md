# report-agent-citation-manager Specification

## Purpose
TBD - created by archiving change extract-report-agent-citation-manager. Update Purpose after archive.
## Requirements
### Requirement: make_cite_key is a pure function deriving a deterministic citation key
`deepear.src.agents.report.citations.make_cite_key(url, title="", source_name="")` SHALL compute its basis as `url.strip()` if non-empty, otherwise `f"{title.strip()}|{source_name.strip()}"`, SHALL return `f"SF-{digest}"` where `digest` is the first 8 hex characters of the SHA-1 hexdigest of that basis encoded as UTF-8, and SHALL therefore return identical keys for identical `(url, title, source_name)` inputs and, for any non-empty `url`, an identical key regardless of `title`/`source_name`.

#### Scenario: Same inputs produce the same key
- **WHEN** `make_cite_key(url="https://example.com/a", title="T", source_name="S")` is called twice with the same arguments
- **THEN** both calls return the same key, and the key starts with `"SF-"`

#### Scenario: A non-empty url determines the key regardless of title/source_name
- **WHEN** `make_cite_key(url="https://example.com/a")` and `make_cite_key(url="https://example.com/a", title="Different", source_name="Different")` are both called
- **THEN** both calls return the same key

#### Scenario: No url falls back to a title-and-source basis
- **WHEN** `make_cite_key(url="", title="Same Title", source_name="Same Wire")` is called twice, and once more with a different `title`
- **THEN** the two calls with identical `title`/`source_name` return the same key, and the call with a different `title` returns a different key

### Requirement: build_bibliography threads its database dependency as an explicit parameter
`deepear.src.agents.report.citations.build_bibliography(signals, *, db)` SHALL require `db` as a keyword-only argument (no default) standing in for the original method's `self.db`, SHALL scan each signal (in order, 1-indexed) for source items via its `sources` attribute/key, or, for a plain dict signal with no `sources`, a single-source entry synthesized from its own `url`/`title`/`source`/`source_name`/`publish_time` fields when either `url` or `title` is present, SHALL derive each source's cite key via `make_cite_key`, SHALL deduplicate bibliography entries by cite key across all signals while still recording every signal index that cites a given key in `signal_to_keys`, SHALL prefer `db.lookup_reference_by_url(url)`'s `url`/`title`/`source`/`publish_time` fields over the signal-provided ones whenever that lookup returns a truthy result for a non-empty `url`, and SHALL fall back to the signal-provided fields (or `"（无标题）"`/`"（未知来源）"` defaults) whenever the lookup returns falsy or `url` is empty.

#### Scenario: Two signals citing the same source dedup to one bibliography entry
- **WHEN** `build_bibliography([signal_one, signal_two], db=db)` is called and both signals cite a source with the same `url`
- **THEN** the returned `bib_entries` contains exactly one entry for that key, and `signal_to_keys` maps both signal indices (`1` and `2`) to a list containing that key

#### Scenario: A successful db lookup overrides signal-provided metadata
- **WHEN** `db.lookup_reference_by_url(url)` returns a dict with a different `title`/`source`/`publish_time` than the signal provided
- **THEN** the corresponding bibliography entry's `title`/`source`/`publish_time` come from the db lookup's dict, not from the signal

#### Scenario: A lookup miss falls back to signal-provided metadata
- **WHEN** `db.lookup_reference_by_url(url)` returns `None` (or `url` is empty)
- **THEN** the corresponding bibliography entry's `title`/`source` come from the signal-provided fields, defaulting to `"（无标题）"`/`"（未知来源）"` if those are also empty

### Requirement: render_references_section and inject_references are pure functions round-tripping a markdown references block
`deepear.src.agents.report.citations.render_references_section(bib_entries, key_to_num)` SHALL return a `"## 参考文献"` markdown block containing `"（无）"` when `bib_entries` is empty, and otherwise one `<a id="ref-{key}"></a>[{num}] {title} ({source}{，publish_time if present}), {url if present}` line per entry (using `"[?]"` when a key has no entry in `key_to_num`), and `deepear.src.agents.report.citations.inject_references(report_md, references_md)` SHALL replace an existing `"## 参考文献"` section (up to the next `"## "` heading or end of text) in place when one is present in `report_md`, and SHALL otherwise append `references_md` at the end of `report_md`.

#### Scenario: Rendering an empty bibliography yields a placeholder
- **WHEN** `render_references_section([], {})` is called
- **THEN** the returned string contains `"## 参考文献"` and `"（无）"`

#### Scenario: Injecting into a report with no existing section appends at the end
- **WHEN** `inject_references(report_md, references_md)` is called and `report_md` contains no `"## 参考文献"` heading
- **THEN** the result is `report_md` followed by `references_md`, and the original content before it is unchanged

#### Scenario: Injecting into a report with an existing section replaces it in place
- **WHEN** `inject_references(report_md, references_md)` is called and `report_md` contains a `"## 参考文献"` section followed by another `"## "` section
- **THEN** the result has exactly one `"## 参考文献"` section (containing `references_md`'s content, not the original placeholder content) and the following section is preserved unchanged

### Requirement: normalize_citations keeps all three required arguments and rewrites all three marker forms
`deepear.src.agents.report.citations.normalize_citations(report_md, signal_to_keys, key_to_num)` SHALL require all three positional arguments (no defaults), consistent with the fix recorded in `openspec/changes/archive/2026-07-23-fix-report-agent-citation-normalize-args/`, and SHALL rewrite three citation marker forms into `[{num}](#ref-{key})` (or `[?](#ref-{key})` when a key is absent from `key_to_num`): legacy `[[n]]` markers (using the first key in `signal_to_keys[n]`, left unchanged if that signal has no keys), `[@KEY]` bracket markers, and loose `(@KEY)`/`（@KEY）` ASCII-or-fullwidth paren-wrapped markers (preserving the original paren characters around the rewritten label).

#### Scenario: A legacy [[n]] marker is rewritten using that signal's first key
- **WHEN** `normalize_citations(text, {1: ["SF-aaaaaaaa", "SF-cccccccc"]}, {"SF-aaaaaaaa": 1})` is called on text containing `"[[1]]"`
- **THEN** the result contains `"[1](#ref-SF-aaaaaaaa)"` and no longer contains `"[[1]]"`

#### Scenario: A legacy marker for a signal with no recorded keys is left unchanged
- **WHEN** `normalize_citations(text, {}, {})` is called on text containing `"[[9]]"`
- **THEN** the result is unchanged, still containing `"[[9]]"`

#### Scenario: Loose ASCII and fullwidth paren-wrapped markers are both rewritten
- **WHEN** `normalize_citations(text, {}, {"SF-aaaaaaaa": 1, "SF-bbbbbbbb": 2})` is called on text containing both `"(@SF-aaaaaaaa)"` and `"（@SF-bbbbbbbb）"`
- **THEN** the result contains `"([1](#ref-SF-aaaaaaaa))"` and `"（[2](#ref-SF-bbbbbbbb)）"`, preserving each marker's original paren style

### Requirement: clean_markdown is a pure function stripping markdown code fences
`deepear.src.agents.report.citations.clean_markdown(text)` SHALL strip leading/trailing whitespace, SHALL then strip a leading ` ```markdown ` fence or a leading bare ` ``` ` fence (checking the `markdown`-tagged form first), SHALL strip a trailing ` ``` ` fence if present, and SHALL leave text with no fences unchanged aside from the leading/trailing whitespace strip.

#### Scenario: A markdown-tagged fence is stripped
- **WHEN** `clean_markdown("```markdown\n# Title\n\ncontent\n```")` is called
- **THEN** it returns `"# Title\n\ncontent"`

#### Scenario: A bare fence is stripped
- **WHEN** `clean_markdown("```\nplain content\n```")` is called
- **THEN** it returns `"plain content"`

#### Scenario: Text with no fence is only whitespace-trimmed
- **WHEN** `clean_markdown("  plain content  ")` is called
- **THEN** it returns `"plain content"`

### Requirement: ReportAgent keeps real delegators of matching binding kind for all six moved names
`ReportAgent._make_cite_key`, `ReportAgent._render_references_section`, `ReportAgent._inject_references`, and `ReportAgent._normalize_citations` SHALL remain real `@staticmethod`s on the class (not bare attribute aliases) that return the corresponding `deepear.src.agents.report.citations` module function's result unchanged, `ReportAgent._build_bibliography(self, signals)` SHALL remain a real bound instance method that returns `deepear.src.agents.report.citations.build_bibliography(signals, db=self.db)`, and `ReportAgent._clean_markdown(self, text)` SHALL remain a real bound instance method that returns `deepear.src.agents.report.citations.clean_markdown(text)`, such that every one of the six remains patchable as a class attribute or instance attribute and every internal call site inside `generate_report`/`_incremental_edit` is intercepted by such a patch.

#### Scenario: Each delegator produces output identical to its module function
- **WHEN** each of the six `ReportAgent` attributes is called with the same arguments as the corresponding module function (using a real `ReportAgent` instance's own `self.db` for `_build_bibliography`)
- **THEN** each pair returns byte-identical/deep-equal results

#### Scenario: Class-level static calls keep working without an instance
- **WHEN** `ReportAgent._make_cite_key(url=..., title=..., source_name=...)` is called directly on the class, with no `ReportAgent` instance constructed
- **THEN** it returns the same key `make_cite_key(url=..., title=..., source_name=...)` would return

#### Scenario: Instance-level calls keep working
- **WHEN** a real `ReportAgent` instance calls `self._build_bibliography(signals)` or `self._clean_markdown(text)` (as `generate_report`/`_incremental_edit` do internally)
- **THEN** each returns the same result the corresponding module function would return given the same inputs (and, for `_build_bibliography`, the instance's own `self.db`)

