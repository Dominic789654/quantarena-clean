## Why

Historical news replay is useful for deterministic backtests, but raw provider exports are not consistently shaped for `FileReplayNewsProvider`. A small fixture builder makes it repeatable to normalize archived JSON, JSONL, or CSV news data into replay fixtures without hitting live APIs.

## What Changes

- Add a news replay fixture builder that reads local JSON, JSONL, or CSV files and writes canonical JSONL rows.
- Normalize common ticker, publish time, title, publisher, URL, and summary field aliases into the replay-provider format.
- Fail clearly on invalid rows by default, with an opt-in mode to skip invalid rows and report counts.
- Validate the generated fixture by loading it through `FileReplayNewsProvider`.
- Expose the builder through the QuantArena CLI.

## Capabilities

### New Capabilities

- `news-replay-fixture-builder`: Build deterministic, provider-compatible news replay fixtures from local archived news exports.

### Modified Capabilities

- None.

## Impact

- Adds a new `quantarena.news_replay_fixture_builder` module.
- Adds a `quantarena provider build-news-replay-fixture` CLI command.
- Adds focused unit and CLI tests for fixture normalization, validation, deterministic output, and invalid-row handling.
- No network dependency and no change to live provider routing.
