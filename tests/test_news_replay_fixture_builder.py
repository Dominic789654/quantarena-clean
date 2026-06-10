"""Tests for building replay news fixtures from archived exports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from backtest.providers import FileReplayNewsProvider
from quantarena.news_replay_fixture_builder import (
    NewsReplayFixtureBuildError,
    build_news_replay_fixture,
)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_build_news_replay_fixture_normalizes_json_array_and_sorts_output(tmp_path: Path) -> None:
    source = tmp_path / "news.json"
    output = tmp_path / "fixture.jsonl"
    source.write_text(
        json.dumps(
            [
                {
                    "symbol": "msft",
                    "headline": "MSFT later",
                    "publishedDate": "2026-06-02T10:00:00-04:00",
                    "site": "FMP",
                    "link": "https://example.com/msft",
                    "sentiment": {"score": 0.4},
                },
                {
                    "symbol": "AAPL",
                    "headline": "AAPL earlier",
                    "publishedDate": "2026-06-01",
                    "site": "FMP",
                    "text": "summary text",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = build_news_replay_fixture(source, output)
    rows = _read_jsonl(output)

    assert result.ok is True
    assert result.input_rows == 2
    assert result.output_rows == 2
    assert result.tickers == ("AAPL", "MSFT")
    assert [row["ticker"] for row in rows] == ["AAPL", "MSFT"]
    assert rows[0]["title"] == "AAPL earlier"
    assert rows[0]["publish_time"] == "2026-06-01T00:00:00Z"
    assert rows[0]["publisher"] == "FMP"
    assert rows[0]["summary"] == "summary text"
    assert rows[1]["url"] == "https://example.com/msft"
    assert rows[1]["sentiment"] == {"score": 0.4}

    provider = FileReplayNewsProvider(output)
    assert provider.get_news("MSFT", datetime(2026, 6, 2), limit=10, market="us")[0]["title"] == "MSFT later"


def test_build_news_replay_fixture_uses_ticker_keyed_json_hints(tmp_path: Path) -> None:
    source = tmp_path / "news.json"
    output = tmp_path / "fixture.jsonl"
    source.write_text(
        json.dumps(
            {
                "aapl": [
                    {
                        "title": "Ticker hinted",
                        "publish_time": "2026-06-01T12:00:00Z",
                        "publisher": "fixture",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = build_news_replay_fixture(source, output)
    rows = _read_jsonl(output)

    assert result.output_rows == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["title"] == "Ticker hinted"


def test_build_news_replay_fixture_normalizes_jsonl_and_csv(tmp_path: Path) -> None:
    jsonl_source = tmp_path / "news.jsonl"
    jsonl_output = tmp_path / "fixture-jsonl.jsonl"
    jsonl_source.write_text(
        "\n".join(
            [
                json.dumps({"ticker": "AAPL", "title": "jsonl row", "publish_time": "2026-06-01"}),
                json.dumps({"symbol": "MSFT", "headline": "jsonl alias", "date": "2026-06-02"}),
            ]
        ),
        encoding="utf-8",
    )
    csv_source = tmp_path / "news.csv"
    csv_output = tmp_path / "fixture-csv.jsonl"
    csv_source.write_text(
        "symbol,headline,publishedDate,source\nAAPL,csv row,2026-06-01,FMP\n",
        encoding="utf-8",
    )

    jsonl_result = build_news_replay_fixture(jsonl_source, jsonl_output)
    csv_result = build_news_replay_fixture(csv_source, csv_output)

    assert jsonl_result.output_rows == 2
    assert _read_jsonl(jsonl_output)[1]["title"] == "jsonl alias"
    assert csv_result.output_rows == 1
    assert _read_jsonl(csv_output)[0]["publisher"] == "FMP"


def test_build_news_replay_fixture_fails_on_invalid_rows_by_default(tmp_path: Path) -> None:
    source = tmp_path / "news.jsonl"
    output = tmp_path / "fixture.jsonl"
    source.write_text(
        json.dumps({"ticker": "AAPL", "title": "bad row", "publish_time": "not-a-date"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(NewsReplayFixtureBuildError, match="invalid news row 1: missing or invalid publish_time"):
        build_news_replay_fixture(source, output)

    assert not output.exists()


def test_build_news_replay_fixture_can_skip_invalid_rows(tmp_path: Path) -> None:
    source = tmp_path / "news.jsonl"
    output = tmp_path / "fixture.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps({"ticker": "AAPL", "title": "valid", "publish_time": "2026-06-01"}),
                json.dumps({"ticker": "MSFT", "title": "bad", "publish_time": "not-a-date"}),
            ]
        ),
        encoding="utf-8",
    )

    result = build_news_replay_fixture(source, output, skip_invalid=True)

    assert result.input_rows == 2
    assert result.output_rows == 1
    assert result.invalid_rows == 1
    assert result.skipped[0].to_dict() == {
        "row_number": 2,
        "reason": "missing or invalid publish_time",
    }
    assert _read_jsonl(output)[0]["ticker"] == "AAPL"
