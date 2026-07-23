# Decomposition Program Plan

Execution-level plan for the four deferred mega-refactors: splitting
`backtest/workflow_adapter.py` (1981 lines), `run.py` (1218),
`deepear/src/agents/report_agent.py` (1661), and consolidating the dual
SQLite layers. Complements [refactor_roadmap.md](refactor_roadmap.md)
(the long-term structural vision); this document covers how to get there
without breaking anything.

Produced 2026-07-23 from a multi-agent analysis (4 per-target dissections,
each adversarially reviewed, then synthesized). Every claim below was
grounded in file:line evidence at the time of writing; re-verify line
numbers before executing a step.

> **Status (2026-07-23): COMPLETE.** All four tracks executed and merged —
> Phase 0 (prereqs), Phase 1 (shared SQLite pragmas), Phase 2 (`run.py` →
> `runner/`, 75-line shim), Phase 3 (`workflow_adapter.py` →
> `backtest/workflow/`, 36-line shim), Phase 4 (`report_agent.py` →
> `deepear/src/agents/report/`, 34-line shim). Suite grew 910 → 1088
> passed / 10 skipped. Every change's OpenSpec artifacts are archived
> under `openspec/changes/archive/2026-07-23-*`. The only deferred steps
> are the optional consumer migrations (steps labeled "optional/deferred"
> per track, e.g. step 32 `migrate-report-agent-direct-consumers`), which
> remove the shims once direct consumers update their imports.

## Ground rules (apply to every step of every track)

1. The full suite must stay green after **every** migration step; each step
   is one PR-sized commit. Sanctioned baseline: run in `.venv_unified`
   (or CI) — 910 passed / 10 skipped at the time of writing. Do not trust
   baselines from ad-hoc interpreters (a system-python run reports phantom
   failures from missing optional deps).
2. Move code **verbatim** unless the step is explicitly labeled a bug fix.
3. Before relocating any function/class, `git grep` every
   `monkeypatch.setattr` / `patch(...)` string touching it, and classify:
   - *module-level bare-global* patches (`monkeypatch.setattr('run.<fn>')`):
     break silently when the **caller** leaves the defining module — route
     the internal call through a `sys.modules.get('run') or
     sys.modules.get('__main__')` shim in the same commit;
   - *class-attribute* patches: survive moves as long as a same-named
     delegator stays on the class.
   This bug class was **reproduced** during planning on
   `tests/test_backtest_fof_config_runtime.py:345`.
4. Public names keep working via re-export shims until consumers migrate
   (deferred, optional final steps).
5. For DB/connection changes, concurrency regression tests must be
   **multiprocess-based** (`ProcessPoolExecutor` is the real production
   pattern), not thread-based.
6. Anything runnable both as `python file.py` and as an import must be
   verified in both modes (fake-executor tests do not cover the
   `__main__` path).

## Sequencing

**Phase 0 (prereqs) → 1 sqlite_layers → 2 run.py → 3 workflow_adapter → 4 report_agent.**

The four tracks share no files, so with a second engineer report_agent
(the largest and least-tested track) can run in parallel from Phase 0.
Rationale for the sequential order: sqlite first because both later
tracks sit on the persistence layer it hardens; run.py second because it
is the cheapest place to bank the monkeypatch-shim discipline that
workflow_adapter's riskiest steps need; report_agent last because its
effort is dominated by building a characterization harness that does not
exist (no test constructs a real `ReportAgent` today).

Effort: ~50 person-days total (~2 prereqs + 6 sqlite + 6 run.py +
14 workflow_adapter + 22 report_agent), ≈ 13–15 weeks solo, ≈ 8–9 weeks
with report_agent parallelized.

## Phase 0 — prerequisites (OpenSpec changes active now)

1. **`pin-agents-package-resolution`** — make `setup_paths()` reorder-if-
   present so `deepfund/src` deterministically precedes `deepear/src`;
   session-scoped pin in conftest; retire per-test-file `sys.path` hacks.
   Unblocks every track whose new leaf modules import `agents.*` lazily.
2. **`fix-report-agent-citation-normalize-args`** — dormant `TypeError`
   found during planning: `report_agent.py:970` calls 3-arg
   `_normalize_citations` with 2 args; only unexercised because zero
   tests build a real `ReportAgent`. Fix + first characterization test
   (seeds the Phase 4 harness).

## Phase 1 — sqlite_layers (~6 days)

Verdict from analysis: a **full merge is not justified** — the two layers
own genuinely distinct domains (deepear: news/signals/invitation/report
persistence; deepfund: config/portfolio/decision/signal for backtests).
The right target is shared low-level infrastructure only.

Changes, in order:
1. `add-shared-db-pragma-helpers` — additive `shared/db/sqlite_pragmas.py`
   (connection pragmas: WAL, busy_timeout, foreign_keys; `ensure_parent_dir`).
2. `adopt-shared-pragmas-in-deepfund-sqlite` — behavior-preserving adoption
   in `sqlite_helper.py`/`sqlite_setup.py`. Gate on the workflow-adapter
   test files (they drive `SQLiteDB` CRUD indirectly).
3. `spike-deepear-importlib-shared-import` — prove `database_manager.py`
   can import `shared.db.*` under all **three** of its load mechanisms
   (normal import, `deepear_client.py`'s `spec_from_file_location` hack at
   lines ~344/350/439, and `technical.py:81-91`'s worker-process import)
   in a fresh process with no prior `setup_paths()`.
4. `add-wal-busytimeout-to-deepear-db` — the one behavior change; ships
   alone, guarded by a **multiprocess** contention regression test.
5. `fix-or-remove-dead-signal-prefetch` — follow-up ticket (dead
   `get_signals_by_date_and_stock` path in
   `multi_personality_engine.py:206-224`), never bundled.

## Phase 2 — run.py → `runner/` package (~6 days)

run.py stays as a thin shim re-exporting every name that tests
monkeypatch by string path. Changes, in order:

6. `extract-run-bootstrap-module` (tushare token patch, dotenv, paths)
7. `extract-run-config-discovery` (`_get_deepfund_config_candidates`,
   `_load_yaml_config_file`, `_select_backtest_config_file`)
8. `extract-run-runtime-options` (backtest/multi-personality resolvers)
9. `add-run-module-shim-and-env-validation` — **the critical step**:
   `runner/_shim.py` (`sys.modules.get('run') or sys.modules.get('__main__')`)
   must land in the same commit that moves `_validate_environment` +
   `_validate_backtest_environment_for_runtime`, and the internal call
   between them must route through the shim, or
   `test_backtest_fof_config_runtime.py::test_llm_backtest_validation_uses_full_env_validator`
   silently stops testing the real path (reproduced during planning).
   Also add a real subprocess smoke (`python run.py --check-env`) — the
   existing fixed-backtest tests never actually exec run.py.
10. `extract-run-cli-support-helpers`
11. `extract-run-mode-handlers-deepear-deepfund-pipeline` (verbatim; add
    `--check-env` and pipeline skip-flag smokes — zero coverage today)
12. `extract-run-backtest-and-multipersonality-modes`
13. `extract-run-cli-entrypoint-package` (`main()`/argparse → `runner/cli.py`)

## Phase 3 — workflow_adapter → `backtest/workflow/` (~14 days)

Structure discovered: two pure dataclasses + two self-contained cache
classes (~570 lines) extract with near-zero risk; scoring functions are
nearly pure; the dangerous mass is the parallel signal-collection engine
and phase-1 pipeline (~900 lines) coupled to adapter state.

Changes, in order:
14. `extract-workflow-pure-dataclasses-and-caches` (BacktestDecision,
    SharedPhase1Artifact, both cache classes — one squashed PR)
15. `extract-workflow-scoring-functions` — note `_calculate_priority_score`
    / `_calculate_signal_consistency` are instance methods whose internal
    `self._signal_label(...)` calls must be rewritten to function calls;
    also switch `test_priority_sorting.py` off its hand-copied shadow
    implementation.
16. `extract-workflow-decision-apply-helpers` (pure statics)
17. `extract-workflow-db-store` (+ new DDL schema-smoke test; none exists)
18. `extract-workflow-company-news-signature-resolver` (keep same-named
    class delegators — tests patch these as class attributes)
19. `add-run-single-day-characterization-test` (happy path, ImportError
    fallback, per-ticker exception fallback — the only untested public
    method)
20. `extract-workflow-signal-collection-engine` — highest risk; ships
    alone; run the suite at least twice (thread-pool nondeterminism)
21. `extract-workflow-phase1-pipeline`
22. `extract-workflow-adapter-core-and-shim`
23. `migrate-workflow-adapter-direct-consumers` (optional/deferred)

## Phase 4 — report_agent → `deepear/src/agents/report/` (~22 days)

Effort is dominated by test infrastructure: **zero tests construct a real
`ReportAgent`** (`test_deepear_workflow.py` stubs the class out entirely).

Changes, in order:
24. `build-report-agent-characterization-harness` — FakeAgent/FakeModel/
    FakeDatabaseManager fixtures (~4–5 days, the long pole; seeded by the
    Phase 0 bug-fix test)
25. `extract-report-agent-retry-helper`
26. `extract-report-agent-pure-chart-and-structured-report-functions`
27. `extract-report-agent-citation-manager`
28. `extract-report-agent-forecast-and-ticker-coordinator` (inject the
    lazy `_get_forecast_agent` callable; add a call-counting test proving
    the Kronos model loads at most once)
29. `extract-report-agent-chart-renderer` — second long pole (460+ lines,
    file I/O, raw SQL, nested throwaway Agent); ships alone with snapshot
    tests; preserve the bare `utils.visualizer`/`utils.stock_tools`
    import spelling verbatim
30. `extract-report-agent-signal-clusterer` (share the exact
    `self.planner` instance by reference; add an identity-assertion test)
31. `finalize-report-agent-package-and-shim` (real `__init__.py` — the
    repo does not use namespace packages)
32. `migrate-report-agent-direct-consumers` (optional/deferred)

## Per-step verification checklist

1. Suite matches baseline before starting.
2. Verbatim move unless labeled a fix.
3. Monkeypatch audit (ground rule 3) for every touched name.
4. Grep new leaf modules for collision-prone bare imports; confirm the
   Phase-0 resolution pin covers them.
5. Add the tests the step's coverage gap calls for — not deferred.
6. Multiprocess concurrency test for any DB change.
7. Both execution modes for dual-mode files.
8. Full suite: exact baseline pass count + newly added tests, zero new
   failures.
9. One PR per step; re-run the suite after any rebase (rebase-merge repo).
10. Shim check: every literal monkeypatch string path still resolves.

## How changes get created

Only active work lives in `openspec/changes/` (Phase 0 is there now).
Create each subsequent change with `/openspec-propose` when its
predecessor merges, copying the step description from this document.
