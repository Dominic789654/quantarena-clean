# Reproduction and Artifact Validation

This document records the current offline checks for QuantArena reproduction assets.
These checks do not call market-data providers, LLM backends, or remote dataset hosts.

## Source Checkout Smoke

Run this after cloning or switching branches:

```bash
python -m quantarena.cli smoke --json
```

The command validates the expected source-checkout layout:

- `backtest/`
- `deepfund/src/config/`
- `deepear/config/`
- `shared/`

It is a repository layout smoke test, not a full package-install or live-market test.

## Artifact Validation

Use the artifact validator before uploading or refreshing a release bundle:

```bash
python -m quantarena.cli evaluate --root release_data --json
```

This is the canonical offline release check. Prefer it over adding new wrapper
commands unless the wrapper removes a concrete source of confusion.

The granular form is also available as
`python -m quantarena.cli artifact validate --root release_data --json`.

The validator checks the local `release_data`-style directory:

- `manifest.json` exists and is valid JSON.
- `croissant.json` exists and is valid JSON.
- Manifest experiments contain either run artifacts or a documented `source_doc`.
- Run entries contain required fields and root-contained file paths.
- Referenced per-run files exist locally.
- Croissant metadata contains core and minimal RAI fields.
- Required Croissant `FileObject`s are present for `manifest.json`, `all_metrics.csv`,
  `all_trades.csv`, and `sector_style_universe.csv`.
- Croissant `FileObject`s include `md5` or `sha256`.
- Local checksums match the Croissant metadata for the top-level distribution files.
- Croissant record fields include source/extract column information.

The command exits with code `0` when there are no validation errors. Warnings are allowed
by default. For example, a documented-only experiment with no redistributed run artifacts
is reported as a warning when its `source_doc` exists inside the artifact root.

## Release-Gate Commands

Run the source-only checks from a clean checkout:

```bash
python -m quantarena.cli smoke --json
python -m pytest tests/test_metrics_contract.py tests/test_artifact_validation.py -q
```

Run the bundle checks when a local `release_data` artifact bundle has been supplied
or restored into the checkout:

```bash
python -m quantarena.cli evaluate --root release_data --json
python -m quantarena.cli evaluate --root release_data --json --summary
```

Use strict mode when the release policy requires warnings to fail the gate:


```bash
python -m quantarena.cli evaluate --root release_data --json --strict
```

Strict mode treats warnings as failures. This is useful when the release policy requires
every experiment in `manifest.json` to have redistributed run artifacts rather than a
documentation-only entry.

## Interpreting JSON Output

The JSON output contains:

- `ok`: overall pass/fail status after applying strict-mode rules.
- `checks`: named boolean checks.
- `errors`: validation failures that always make the command fail.
- `warnings`: non-fatal findings unless `--strict` is enabled.
- `stats`: counts such as manifest experiments, validated runs, missing files, and checked hashes.
- `strict`: whether warning promotion was enabled for this run.

Downstream scripts should treat `ok`, `checks`, `errors`, `warnings`, and `stats`
as the stable top-level contract. Individual `checks` keys may expand as the
artifact validator learns new release requirements, but existing keys should not
change meaning without a matching test update.

Current expected local behavior for the submitted artifact bundle is:

```text
ok: true
manifest_runs: 28
warnings: exp5_efficiency_ablation_cn_10t_6m is documented-only
```

The summary mode returns a compact schema with `summary_schema_version: 1`,
experiment/run counts, Croissant distribution counts, and warning categories. It is
intended for dashboards, handoff notes, and quick pre-submit inspection; it does not
replace validation.

## Artifact Summary

Use the summary command when you only need a quick overview:

```bash
python -m quantarena.cli evaluate --root release_data --json --summary
```

The granular form is also available as
`python -m quantarena.cli artifact summary --root release_data --json`.

The summary reports:

- experiment count
- run count
- documented-only experiment count
- Croissant FileObject count
- any documented-only warnings

The summary is intentionally non-failing and is meant for quick pre-submit checks.

## What This Does Not Validate

This command intentionally does not:

- Download from Hugging Face or any other dataset host.
- Run the online Croissant validator.
- Re-run backtests.
- Contact market-data providers.
- Contact LLM APIs.
- Validate full Croissant schema semantics beyond the local fields needed for this bundle.

Provider, LLM, and end-to-end backtest changes need separate opt-in real API smoke checks.

## Provider Smoke Checks

Provider-facing changes can run an opt-in live daily-candle smoke check:

```bash
python -m quantarena.cli provider smoke --market us --provider fmp --ticker AAPL --date 2026-01-02 --json
```

The command checks credentials before making a request. Missing credentials are reported as
a clean skip with exit code `0`; provider errors or empty responses exit non-zero. Supported
credential variables are `FMP_API_KEY`, `ALPHA_VANTAGE_API_KEY`, and `TUSHARE_API_KEY`.
