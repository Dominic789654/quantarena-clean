## 1. Core Builder

- [x] 1.1 Add a news replay fixture builder module with JSON, JSONL, and CSV input readers.
- [x] 1.2 Normalize ticker, publish time, title, publisher, URL, summary, and JSON-safe metadata aliases.
- [x] 1.3 Write deterministic canonical JSONL output and validate it with `FileReplayNewsProvider`.

## 2. CLI Integration

- [x] 2.1 Add `quantarena provider build-news-replay-fixture` parser arguments.
- [x] 2.2 Dispatch the CLI command with JSON and human-readable result output.

## 3. Verification

- [x] 3.1 Add focused builder and CLI tests for supported formats, deterministic output, validation, and invalid-row handling.
- [x] 3.2 Run OpenSpec validation and focused test suite.
