# QuantArena CLI Reference

The stable utility CLI is available as `quantarena` (after `pip install -e .`)
or `python -m quantarena.cli`. All commands below work without network access
unless noted; commands that support `--json` emit machine-readable output.

## Repository and artifact checks

```bash
quantarena smoke --json                      # validate this source checkout layout
quantarena evaluate --root release_data --json [--strict]   # validate + summarize a release bundle
quantarena artifact validate --root release_data --json     # granular validation only
quantarena artifact summary  --root release_data --json     # summary only
```

`evaluate --strict` turns validation warnings into failures; use it as the
release gate when a local `release_data/` bundle is present. See
[reproduction.md](reproduction.md) for what these checks do and do not cover.

## Reports

```bash
quantarena report visualize --report-dir reports/backtest/<run_id>
```

Generates a standalone HTML visualizer for one backtest report directory.
Each report directory also contains `run_manifest.json` (git provenance,
experiment definition, aggregated LLM token usage and estimated cost).

## Providers and caches

```bash
quantarena provider smoke --json             # minimal live daily-candle check;
                                             # skips cleanly without credentials
quantarena provider build-news-replay-fixture ...   # build deterministic news replay fixtures
quantarena cache health --json               # report cache readiness without live fetches
quantarena cache warmup [--fixed] --json     # plan (fixed-benchmark) cache warmup actions
```

Deterministic replay knobs live in `.env` (see `.env.example`):
`COMPANY_NEWS_PROVIDER=replay` for news, and
`APEWISDOM_SNAPSHOT_MODE` / `SEC_EDGAR_SNAPSHOT_MODE` for alt-data
(`refresh` accumulates daily snapshots; `local_only` replays them offline).

## Live read-only broker

```bash
quantarena live contract                     # print the provider contract
quantarena live smoke --json                 # deterministic snapshot-based smoke check
quantarena live account | positions | orders | quotes
```

`live` is strictly read-only: it observes account/position/order/quote state
through the provider adapter (`--provider`, `--snapshot`) and never places
orders.

## Paper trading

```bash
quantarena paper init                        # initialize state (data/paper_portfolio/state.json)
quantarena paper smoke --json                # deterministic paper-portfolio smoke check
quantarena paper account | positions | orders
quantarena paper quote set AAPL 190.5
quantarena paper quote list
quantarena paper order submit --symbol AAPL --side buy --shares 10
quantarena paper order fill <order_id> ; quantarena paper order cancel <order_id>
quantarena paper reconcile --cash 98095.0 --position AAPL:10
```

`paper` simulates a broker with order lifecycle, risk checks, and an audit
trail; `--state` overrides the state-file path. Backtests reuse the same
paper-broker execution layer and emit `broker_audit.jsonl` per run.

## Research runner

Experiment workflows (DeepEar, DeepFund, backtests, multi-policy runs) go
through the research runner rather than this CLI:

```bash
quantarena run --help        # stable wrapper
python run.py --help         # direct runner
```

Matched experiment universes for paper-style backtests live at
`deepfund/src/config/ashare_experiment_universe.yaml` and
`deepfund/src/config/us_experiment_universe.yaml`; pass them via `--config`.
