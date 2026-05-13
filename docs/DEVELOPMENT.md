# Development Workflow

This repository is moving from a research codebase toward a reproducible engineering
codebase. Development should preserve submitted results while making runtime paths
smaller, clearer, and easier to test.

## Branch and PR Rules

- Work on a feature branch. Do not commit directly to `main`.
- Merge through GitHub PRs.
- Keep each PR scoped to one issue or one clearly bounded cleanup.
- Every PR must describe:
  - behavior impact
  - tests run
  - reproduction risk
  - whether real API smoke checks were needed
- Do not include generated reports, local logs, paper build outputs, release mirrors,
  zip bundles, credentials, or notebook/prototype outputs.
- Preserve unrelated local or user changes. If the working tree is dirty, inspect before
  editing and avoid staging unrelated files.

## Default Local Checks

Run the no-network smoke check after changing CLI, path, package, or repository-boundary
code:

```bash
python -m quantarena.cli smoke --json
```

Run focused tests for changed modules, plus shared regressions when a change touches
cross-cutting behavior. Examples:

```bash
pytest tests/test_quantarena_cli.py tests/test_artifact_validation.py -q
pytest tests/test_profile_registry.py tests/test_provider_routing.py -q
pytest tests/test_backtest_engine_factory.py tests/test_run_config_selection.py -q
```

Before merging changes that touch reproduction tooling, run:

```bash
python -m quantarena.cli evaluate --root release_data --json
python -m quantarena.cli evaluate --root release_data --json --summary
```

Use strict mode only when warnings should fail the release gate:

```bash
python -m quantarena.cli evaluate --root release_data --json --strict
```

These commands require a local `release_data` bundle. If the bundle is unavailable in a
fresh checkout, document the skip in the PR and rely on the focused unit tests for that
change.

## Real API Smoke Policy

Default tests must not require credentials or network access.

Run real API smoke checks only when a PR changes provider, LLM, or end-to-end execution
behavior:

- Provider routing or provider implementations: one tiny US/CN data fetch when credentials
  are available.
- LLM routing or response parsing: one minimal prompt against the selected backend when
  credentials are available.
- Engine execution changes: one 2-5 trading day tiny-universe run, preferably through
  replay/offline fixtures first.

Use personal or sandbox credentials for smoke checks. Keep cost, quota, and rate limits
small; if credentials are unavailable, document the skip in the PR instead of hiding the
gap.

## Formatting and Static Checks

When a PR changes Python source, run the relevant formatter, linter, or type checks used
by that part of the repository. Prefer focused checks over broad cleanup. If a check is not
configured for the touched module yet, say so in the PR rather than adding unrelated
format churn.

## Review Agent Policy

Use a code-review agent before merging PRs that touch:

- runtime execution
- provider or LLM routing
- artifact validation or release tooling
- shared tests or compatibility layers
- broad documentation that defines project workflow

The review request should be read-only and should ask for findings first, ordered by
severity, with file and line references. Blocking findings must be fixed before merge;
run a focused re-review when the fix is non-trivial.

## Extension Points

Use the existing compatibility layers when adding new behavior. Avoid wiring a new
mandate or provider directly into only one script.

### Investment Mandates and Profiles

Start with the canonical profile registry:

- `shared/config/profile_registry.py` maps legacy aliases to canonical profile names.
- `backtest/engine.py::_resolve_backtest_engine_route` maps a profile to the engine
  class that should execute it.
- `backtest/mandate_interface.py` defines the allocator protocol used by engines that
  delegate portfolio allocation.
- Existing mandate-specific engines are in `backtest/fundamental_value_engine.py`,
  `backtest/macro_tactical_engine.py`, `backtest/behavioral_momentum_engine.py`,
  `backtest/smart_beta_engine.py`, and `backtest/fof_engine.py`.

When adding a mandate or alias:

- Add the canonical name and aliases to `shared/config/profile_registry.py`.
- Route the profile in `_resolve_backtest_engine_route` only if it needs a distinct
  engine. If the default `BacktestEngine` is enough, keep the route unchanged.
- Prefer implementing allocation behind `MandateAllocator` when the mandate changes
  target weights rather than shared accounting.
- Add focused tests for alias normalization, engine routing, allocation constraints,
  and any changed report metrics.
- Run `python -m quantarena.cli smoke --json` and the focused profile/engine tests.

### Market Data and Replay Providers

Provider-facing code should stay behind explicit provider interfaces:

- `backtest/providers.py` defines `DailyCandleProvider`, `NewsProvider`,
  `FundamentalsProvider`, `MacroProvider`, typed provider failures, and replay
  providers used by offline tests.
- `shared/config/provider_routing.py` normalizes US/CN provider names and owns the
  current US default/preference helpers.
- `backtest/data_loader.py` consumes injected daily-candle and news providers.
- `deepfund/src/apis/router.py` is the legacy live-router boundary for existing API
  adapters.

When adding or changing a provider:

- Add or reuse a protocol in `backtest/providers.py`.
- Add replay fixtures before live API behavior so default tests stay offline.
- Add provider-name normalization or routing changes in `shared/config/provider_routing.py`.
- Keep provider failures structured and sanitized through `ProviderFailure`.
- Run focused provider tests and `python -m quantarena.cli provider smoke ... --json`
  when credentials are available. If credentials are unavailable, document the skip in
  the PR.

## Reproduction Boundary

Submitted-paper and release assets are not runtime package code. Keep these boundaries:

- `release_data/`: local release mirror and validation target; ignored by git.
- `latex/`: local paper workspace; ignored by git.
- `reports/`, `experiments/`, `data/cache/`: generated or local runtime artifacts.
- `quantarena/`: tracked source package for stable CLI entry points.

Do not ignore the top-level `quantarena/` package. It contains tracked source files.

## Artifact Validation

See [reproduction.md](reproduction.md) for the current artifact validation workflow.

The offline validator checks local manifest and Croissant metadata, required top-level
files, checksums, and run-file references. It does not replace:

- online Croissant validation
- dataset-host accessibility checks
- live API smoke tests
- full backtest re-runs
- full figure/table regeneration

## PR Checklist

Use the repository PR template. At minimum, every PR should answer:

- What changed?
- What behavior changes?
- What tests ran?
- Was a real API check needed?
- What reproduction risk remains?

## Commit Messages

Use concise conventional prefixes:

```text
feat: add artifact summary command
fix: isolate api source fallback test from local env
refactor: centralize provider routing helpers
docs: record phase 6 artifact validation status
test: harden artifact validation edge cases
chore: update roadmap issue status
```

## Local Workspace Hygiene

Local helper files may exist during paper or artifact work. Keep them untracked unless they
are intentionally part of a PR. Before committing, run:

```bash
git status -sb
git diff --check
```

Stage files explicitly rather than using broad `git add .` when local artifacts are present.
