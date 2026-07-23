## Context

`deepear/src/agents/report_agent.py`'s `ReportAgent` class has two
staticmethods that, unlike `_run_agent_with_retry` (step 25), touch no
`self.LLM_*` constants or any other instance/class state:

- `_sanitize_json_chart_blocks(text)` (~170 lines including its nested
  `find_json_end` helper): a two-phase best-effort repair for malformed
  ```` ```json-chart ```` fenced blocks the LLM sometimes emits (Phase 0
  normalizes several opening/closing-fence typo variants line-by-line;
  Phase 1 finds the first balanced-brace JSON object after each opening
  fence and inserts a closing fence if one is missing).
- `build_structured_report(report_md, signals, clusters)` (~70 lines): a
  pure markdown-to-JSON shaper -- pulls the title from the first `# ` line,
  splits the body into `#{2,4}`-heading sections (with an implicit leading
  "摘要" section for any preamble), extracts bullet-list summary points
  (capped at 8), and builds a `signal_map`/`structured_clusters` pair from
  the `signals`/`clusters` arguments using `hasattr`/`getattr` fallbacks so
  either plain dicts or attribute-bearing objects work.

`grep -n "self\." deepear/src/agents/report_agent.py`, restricted to each
method's body (lines 507-675 and 711-782 respectively, before this change),
returns zero matches for both. Neither method reads `self.db`, `self.model`,
`self.rag`, any `LLM_*` constant, or any other collaborator -- they operate
purely on their own parameters and locals.

## Goals / Non-Goals

**Goals:** move both bodies verbatim into two new pure-function leaf
modules; keep both `ReportAgent` staticmethods as real class attributes
(one-line delegators) so every existing call site and monkeypatch
opportunity keeps working; add direct tests for fence-normalization
variants and structured-report field mappings the characterization suite
doesn't already cover; add a delegation-regression test.

**Non-Goals:** touching `_clean_markdown` (~line 991 after this change),
`_make_cite_key`, `_render_references_section`, or `_inject_references`
(all belong to step 27, `extract-report-agent-citation-manager`) even
though they sit textually close to `build_structured_report`; changing any
repair heuristic, fence-variant list, section-parsing regex, bullet-marker
set, or the 8-item summary-bullet cap; building out
`deepear/src/agents/report/__init__.py` re-exports (deferred to step 31).

## Decisions

1. **Both become pure module-level functions with unchanged signatures.**
   Because neither method reads `self.` state, ground rule 6's
   parameter-threading requirement is vacuous here -- there is nothing to
   thread. `sanitize_json_chart_blocks(text)` and `build_structured_report
   (report_md, signals, clusters)` keep the exact parameter names, order,
   and defaults (none) the original methods had. This is the simplest
   possible case of the pattern `retry.py` established: `self.` reads
   become parameters when present, and are simply absent when they aren't.
2. **`build_structured_report`'s module import is aliased to avoid name
   shadowing, `sanitize_json_chart_blocks` is not.** The module function
   `deepear.src.agents.report.structured_report.build_structured_report`
   shares its exact name with the class staticmethod
   `ReportAgent.build_structured_report` (the retry-helper precedent,
   `run_agent_with_retry` vs. `_run_agent_with_retry`, had a leading-
   underscore difference that made this a non-issue). Class-body method
   definitions do not create a new lexical scope that shadows the module
   global namespace -- a `def build_structured_report(...):` inside the
   `class ReportAgent:` body only binds a class attribute, so the module-
   level import name remains resolvable from within any function body in
   the module, including the staticmethod's own -- but importing under an
   alias (`as _build_structured_report_impl`) is strictly clearer to a
   reader scanning the `import` block and avoids relying on that scoping
   subtlety being obvious. `sanitize_json_chart_blocks` needs no alias
   because its name already differs from `_sanitize_json_chart_blocks`.
3. **Two separate leaf modules, not one.** `chart_sanitizer.py` and
   `structured_report.py` have no shared helpers and no reason to import
   from each other; splitting them mirrors how `retry.py` was scoped to
   exactly one method, and keeps each new module's docstring focused on
   one self-contained algorithm (fence repair vs. markdown shaping) rather
   than describing two unrelated things in one file.
4. **Class keeps real staticmethods, not bare attribute aliases.**
   Following the retry-helper precedent (decision 4 there), each delegator
   is a normal one-line-body `@staticmethod def ...` rather than `_sanitize_
   json_chart_blocks = staticmethod(chart_sanitizer.sanitize_json_chart_
   blocks)`. Either form would behave identically for direct calls (`grep`
   found no monkeypatch of either name in the repo today, so this is a
   forward-looking choice, not a fix for an existing patch), but a real
   `def` reads slightly clearer next to `_run_agent_with_retry`'s own
   delegator body one method above it in the same file, and keeps the
   pattern uniform across all of Phase 4's staticmethod extractions.
5. **New test file, not an extension of the characterization suite** (same
   rationale as retry-helper decision 5): `tests/test_report_pure_functions
   .py` is new. It imports the module functions directly for the bulk of
   its coverage and only reaches for `tests/report_agent_harness.py`'s
   `make_report_agent` in the one delegation-regression test that needs a
   real `ReportAgent` instance.

## Risks / Trade-offs

- `build_structured_report`'s name-shadowing situation (decision 2) is
  subtle enough that a future contributor might "simplify" the import by
  removing the alias, assuming it causes a `NameError` or infinite
  recursion. The design comment and this change's own delegator docstring
  in `report_agent.py` both call this out; the alias is also enforced by
  ruff's unused-import / redefinition checks staying clean either way, so
  there's no automated guard beyond the comment.
- Splitting into two modules instead of one slightly increases the leaf-
  module count for what is a small amount of code; accepted because it
  matches the one-algorithm-per-module shape used everywhere else in this
  refactor (`backtest/workflow/scoring.py`, `.../decision_apply.py`, etc.)
  and keeps each module's docstring and future citation-manager work
  (step 27, which will add a third, related-but-distinct module) cleanly
  separated.
