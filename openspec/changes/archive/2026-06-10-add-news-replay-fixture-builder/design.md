## Context

`FileReplayNewsProvider` already loads ticker-keyed JSON or per-row JSONL fixtures for deterministic news replay. Raw historical news exports commonly arrive as JSON arrays, JSONL dumps, CSV exports, or provider-specific objects with field aliases such as `symbol`, `publishedDate`, `site`, and `text`, so replay setup currently requires manual reshaping.

## Goals / Non-Goals

**Goals:**

- Convert local JSON, JSONL, or CSV news exports into replay-provider-compatible JSONL.
- Normalize common field aliases while preserving additional JSON-safe metadata.
- Make output deterministic so generated fixtures are stable in tests and diffs.
- Validate generated fixtures by loading them with `FileReplayNewsProvider`.
- Expose a CLI entry point for repeatable local use.

**Non-Goals:**

- Fetch historical news from live APIs.
- Add provider-specific network clients or credential handling.
- Change `FileReplayNewsProvider` filtering behavior.
- Build a full ETL framework for all possible vendor schemas.

## Decisions

- Implement the builder as `quantarena.news_replay_fixture_builder` with a small dataclass result. This keeps parsing and validation independently testable, while the CLI only handles argument parsing and output.
- Support three local formats: JSON array/object, JSONL rows, and CSV. JSON object inputs may be ticker-keyed (`{"AAPL": [...]}`) or contain common collection keys such as `articles`, `news`, `data`, or `results`.
- Write canonical JSONL rows with `ticker`, `title`, `publish_time`, `publisher`, optional `url`, optional `summary`, and preserved extra scalar/list/dict metadata when JSON serializable. JSONL is the common denominator already accepted by `FileReplayNewsProvider`.
- Require each output row to have a non-empty ticker, non-empty title, and parseable publish time. Invalid rows fail the build by default; `skip_invalid=True` / `--skip-invalid` records and skips them.
- Sort rows by ticker, publish time, and title before writing. This makes generated fixtures deterministic across input order and file format.
- Validate the written file by constructing `FileReplayNewsProvider(output_path)`. This avoids silently producing fixtures that the replay provider cannot load.

## Risks / Trade-offs

- Provider schemas can vary beyond common aliases -> fail with row-numbered errors so adding a mapping is straightforward.
- Strict validation may reject messy raw exports -> `--skip-invalid` allows exploratory fixture generation while keeping default CI behavior strict.
- Preserving arbitrary metadata can leak unwanted local notes -> only local files are read and no credentials are fetched; users can inspect JSONL output before sharing.

## Migration Plan

No migration is required. Existing replay fixtures continue to load unchanged. New fixtures can be generated explicitly through the CLI or module API.
