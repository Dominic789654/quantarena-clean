# QuantArena Refactor Roadmap

This roadmap defines how to turn the current research repository into a simpler, testable, and reproducible engineering codebase.

## Goals

- Preserve paper reproduction behavior before changing internals.
- Make the runtime package small, explicit, and easy to install.
- Replace historical `personality` naming with `mandate` / `policy` terminology through compatibility layers.
- Separate code, experiments, release data, paper assets, and generated reports.
- Require tests for every refactor PR and real API checks for provider-facing changes.

## Non-Negotiable Development Rules

- Work on feature branches and merge through PRs.
- Every PR must list behavior impact, tests run, and reproduction risk.
- Unit tests are required for changed modules.
- Critical provider, engine, and LLM-routing changes need at least one real API smoke check when credentials are available.
- Paper-result regression checks must guard released metrics, trade logs, and figure/table source data.
- No generated reports, temporary figures, local logs, credentials, or notebook/prototype outputs should enter the core package.

## Target Structure

```text
quantarena/
  src/quantarena/
    mandates/          # FV, MT, BM, LV, EqW policy definitions
    harness/           # execution loop, portfolio tracker, reports
    analysts/          # shared analyst interfaces and implementations
    providers/         # market-data and news providers
    llm/               # backend routing and replay
    metrics/           # performance and behavior metrics
    config/            # typed config schemas and defaults
    cli/               # quantarena smoke/run/evaluate
  tests/
  configs/
  docs/
  examples/
```

Long-term, `latex/`, `release_data/`, `reports/`, and exploratory scripts should remain outside the importable package.

## Phased Plan

### Current Status

The initial refactor pass has landed through PRs #92-#116. Phases 0-5 now
have their core protections or compatibility layers in place:

- Phase 0: baseline metric regression checks were added in #93.
- Phase 1: repository-boundary artifact guards were added in #94.
- Phase 2: source-checkout smoke, run, and evaluate CLI entry points were added
  in #95, #105, and #106.
- Phase 3: profile/mandate alias normalization was centralized in #96.
- Phase 4: engine factory, mandate allocation, target execution, order execution,
  and snapshot helpers were introduced in #97 and #107-#110.
- Phase 5: provider routing, replay providers, provider smoke checks, typed
  provider failures, and provider-facing regression tests were completed in
  #98 and #111-#116.

Phase 6 has been hardened through #119-#125. Phase 7 developer workflow
documentation is covered by #100, #103, #104, #125, the final extension-guide
slice in #126, and the roadmap-completion update in #127.

Post-roadmap hardening has also landed:

- #128 fixed the live-LLM allocator alias initialization bug that escaped
  stubbed tests.
- #129 kept the default installation lightweight by moving heavy ML packages
  such as `torch`, `transformers`, and `sentence-transformers` behind the
  optional `.[ml]` extra.
- #130 moved backtest environment validation after runtime resolution so
  deterministic non-LLM backtests are not blocked by LLM credentials, while
  LLM backtests still use the full environment validator.

Current closure status:
- Complete. The refactor roadmap is now in maintenance mode. Future work should
  be handled as scoped feature, release, or provider-hardening PRs rather than
  extending this roadmap.

### Phase 0: Baseline Protection

- Define a minimal reproducibility contract for the submitted paper numbers.
- Add tests for deterministic smoke runs, released metric loaders, and key table/figure source data.
- Add CI commands for unit tests, lint, and smoke test.
- Freeze a small set of golden outputs for EqW, LV, and selected mandate behavior metrics.

Acceptance:
- `pytest tests` passes.
- A documented smoke command runs without credentials.
- A regression script verifies core released tables against expected hashes or row-level checks.

### Phase 1: Repository Boundary Cleanup

- Move generated reports, local logs, old zips, paper-only assets, and release mirrors out of the default development path.
- Add `.gitignore` rules for generated artifacts.
- Document which directories are source, paper, release, generated, or archival.
- Keep `latex/` and `release_data/` clearly documented as submission assets, not runtime package code.

Acceptance:
- `git status` after normal tests is clean except intentional outputs.
- No generated reports or temporary figures are required for package import or smoke tests.

### Phase 2: Package and Entry-Point Standardization

- Choose one canonical package layout.
- Add CLI entry points:
  - `quantarena smoke`
  - `quantarena run --market us --mandate macro_tactical ...`
  - `quantarena evaluate --config configs/us_6m.yaml`
- Make installation reproducible through `pyproject.toml`.
- Remove duplicate or stale setup paths after compatibility tests pass.

Acceptance:
- Fresh venv install works.
- CLI smoke test passes with replay fixtures.
- Existing programmatic engine API remains available or has documented deprecation wrappers.

### Phase 3: Naming Migration

- Introduce `mandate` as the canonical domain term.
- Keep compatibility aliases for `personality` until downstream scripts are migrated.
- Rename config keys, file names, and docs gradually.
- Add tests proving legacy aliases map to the same mandates.

Acceptance:
- No user-facing docs rely on `personality` for current concepts.
- Compatibility tests cover old names.

### Phase 4: Engine and Harness Simplification

- Separate policy decision logic from shared execution accounting.
- Make all mandates implement one explicit interface.
- Remove duplicated engine code by pushing common behavior into the harness.
- Keep deterministic policies free of LLM imports.

Acceptance:
- Mandate unit tests cover allocation constraints, cash handling, turnover behavior, and accounting.
- Engine regression tests show unchanged smoke and selected paper-derived metrics.

### Phase 5: Provider and LLM Routing Cleanup

- Normalize provider interfaces for price, fundamentals, news, and macro data.
- Add replay providers for offline tests.
- Move real API checks into opt-in tests marked clearly.
- Make provider failures explicit and typed.

Current implementation:
- Provider source selection is centralized and covered by routing/config tests
  (#98).
- Offline replay providers exist for daily candles, company news, fundamentals,
  and macro indicators (#111, #113, #115, #116).
- `DataPrefetcher` supports replay daily-candle and news providers while
  preserving default Router/Tushare/FMP live paths (#111, #113).
- `FundamentalAnalyst` and `MacroTacticalBacktestEngine` support opt-in replay
  provider injection while keeping their default Router paths unchanged (#115,
  #116).
- `python -m quantarena.cli provider smoke ...` provides credential-aware,
  opt-in live provider checks with clean skip behavior when keys are absent
  (#112).
- Provider failures are captured as sanitized structured records in prefetch
  paths (#114).
- Focused tests cover default provider routing, replay payload normalization,
  injected-provider behavior, and provider failure fallback paths.

Future non-blocking cleanup:
- LLM replay/provider abstractions remain a useful long-term addition, but they
  are not required to close the current market-data provider cleanup.
- Additional live provider smoke coverage can be added when CN/US credentials
  are available in a controlled environment.

Acceptance:
- Offline tests never require credentials.
- Real API smoke checks can be run with documented env vars.
- Provider selection behavior is covered by unit tests.

### Phase 6: Reporting, Metrics, and Reproducibility Tools

- Move figure/table regeneration into a separate reproducibility tool layer.
- Keep metrics pure and independently testable.
- Add validation commands for release artifacts and Croissant metadata.
- Make report generation optional and separated from core run execution.

Current implementation:
- Paper-facing metric contracts and release-data regression tests cover key
  return, risk, cash, turnover, and holding-period fields.
- Run-level report artifact loading is centralized in `quantarena.report_artifacts`
  and reused by behavior fallbacks, comparison regeneration, and multi-personality
  report summaries.
- Offline artifact evaluation is available through
  `python -m quantarena.cli evaluate --root release_data --json`.
- Strict release-gate validation is available through
  `python -m quantarena.cli evaluate --root release_data --json --strict`.
- Quick bundle inspection is available through
  `python -m quantarena.cli evaluate --root release_data --json --summary`.
- The current tool layer validates local manifests, Croissant core/RAI fields, required
  FileObjects, local checksums, root-contained run file references, and documented-only
  experiment warnings.
- These checks are intentionally offline. They do not replace the online Croissant
  validator, dataset-host accessibility checks, live API smoke tests, or full backtest
  re-runs.
- Phase 6 keeps the CLI surface small: `evaluate` is the canonical offline entry
  point, while `artifact validate` and `artifact summary` remain granular aliases.

Planned PR slices:

1. Phase 6.1: metrics contract and golden regression. Complete.
   - Define the paper-facing metric contract for key performance and behavior
     fields, including units, rounding, nullable values, and expected source
     files.
   - Add release-data regression tests for `derived/all_metrics.csv` and selected
     run-level `metrics.json` files, using either a supplied local release bundle
     or small checked-in fixtures when the full bundle is unavailable.
   - Cover `total_return`, `max_drawdown`, `volatility`, `sharpe_ratio`,
     `avg_cash_ratio`, `avg_turnover_ratio`, and `avg_position_days` without
     changing metric semantics.
2. Phase 6.2: artifact summary normalization. Complete.
   - Stabilize the JSON schema returned by `evaluate --summary` so it can be used
     in CI, handoff notes, and release checks.
   - Report experiment counts, run counts, documented-only experiments, Croissant
     FileObject counts, and warning categories consistently.
   - Preserve existing `evaluate --strict` behavior.
3. Phase 6.3: report-generation boundary. Complete.
   - Separate artifact loaders and pure summary helpers from report-writing side
     effects.
   - Keep backtest execution independent from report generation, especially when
     `generate_report=False`.
   - Add focused tests around behavior-metric fallback, benchmark reporting, and
     comparison-report regeneration.
4. Phase 6.4: reproducibility CLI and documentation polish. Complete.
   - Document the stable offline release checks and their JSON outputs.
   - Keep the CLI surface small, either by extending `evaluate` or adding a thin
     `reproduce check` alias only if it reduces confusion.
   - Mark Phase 6 complete only after the offline commands, docs, and regression
     tests protect submitted artifact behavior.

Acceptance:
- Metrics tests cover return, drawdown, Sharpe, cash ratio, turnover, and holding period.
- Source-checkout smoke and focused metrics/artifact tests run from a clean checkout.
- Bundle validation and summary checks run when a local `release_data` artifact bundle
  has been supplied or restored.
- Phase 6 PRs run the offline source smoke check, artifact validation, artifact
  summary, and focused metrics/report tests relevant to each change.
- Strict artifact validation is the release-gate target; it may remain red while
  documented-only experiment warnings are intentionally present.
- Real API checks are not required unless a Phase 6 change touches provider or LLM
  behavior.

### Phase 7: Documentation and Developer Workflow

- README covers install, smoke checks, CLI entry points, repository layout, and
  architecture-oriented documentation links.
- `docs/DEVELOPMENT.md` records branch/PR/test/API-check rules and extension
  points for mandates, profiles, and providers.
- `docs/reproduction.md` records paper and artifact validation checks.
- `.github/pull_request_template.md` captures behavior impact, tests, API checks,
  reproduction risk, safety, and review-agent status.

Acceptance:
- Complete: a new developer can install, run the smoke test, follow the PR workflow,
  and find where to add a mandate or provider.

## Clean Public Repository Handoff

The current repository contains the full development history, including research
iterations, paper-submission work, temporary branches, and implementation trails.
If the final code is released in a new public repository, do not fork or mirror
this repository directly when commit history should remain private.

Recommended handoff:

1. Export the current tracked tree into a clean directory without `.git`
   history.
2. Exclude local-only paths and generated artifacts such as `.env`, `reports/`,
   `data/`, `latex/`, `release_data/`, temporary zips, logs, caches, and local
   validation reports.
3. Run the fresh-install checks in the clean directory before the first public
   commit:
   - `python -m pip install -e .`
   - `python -m quantarena.cli smoke --json`
   - focused unit tests for CLI, provider routing, artifact validation, and
     backtest runtime validation.
4. Create the new repository with a single initial commit from the sanitized
   export.
5. Add release data through the intended dataset host or a separate sanitized
   artifact channel, not through the source repository history.

This keeps the final codebase reproducible while avoiding exposure of private
development commits, local artifact churn, or paper-submission history.

## PR Slicing

Recommended order:

1. Baseline tests and golden checks.
2. Ignore/generated-artifact cleanup.
3. Fresh-install and smoke-test dependency fixes.
4. CLI smoke entry point.
5. Mandate naming compatibility layer.
6. Provider replay interface cleanup.
7. Engine interface extraction.
8. Metrics contract and golden release-data regression.
9. Artifact summary normalization.
10. Report-generation boundary cleanup.
11. Reproducibility CLI and documentation polish.
12. Documentation refresh.

## Real API Check Policy

Use real API checks only for changes that touch provider or LLM behavior:

- Market provider routing: one US and one CN ticker fetch if credentials exist.
- LLM routing: one minimal prompt to the selected backend or a documented skip.
- End-to-end engine path: one short 2-5 day run with tiny universe.

All real API checks must be opt-in, rate-limited, and excluded from default CI.
