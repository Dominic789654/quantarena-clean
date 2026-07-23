"""Build deterministic file replay news fixtures from local exports."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from backtest.providers import FileReplayNewsProvider


TICKER_FIELDS = ("ticker", "symbol", "stock", "code")
TITLE_FIELDS = ("title", "headline", "name")
PUBLISH_TIME_FIELDS = ("publish_time", "published", "publishedDate", "published_date", "date", "datetime", "time")
PUBLISHER_FIELDS = ("publisher", "source", "site", "provider")
URL_FIELDS = ("url", "link")
SUMMARY_FIELDS = ("summary", "text", "content", "description")
COLLECTION_FIELDS = ("articles", "news", "data", "results", "items")

CANONICAL_FIELDS = {"ticker", "title", "publish_time", "publisher", "url", "summary"}
ALIAS_FIELDS = set(
    TICKER_FIELDS
    + TITLE_FIELDS
    + PUBLISH_TIME_FIELDS
    + PUBLISHER_FIELDS
    + URL_FIELDS
    + SUMMARY_FIELDS
)


class NewsReplayFixtureBuildError(ValueError):
    """Raised when a replay fixture cannot be built."""


@dataclass(frozen=True)
class InvalidNewsRow:
    """One invalid input row encountered during fixture building."""

    row_number: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"row_number": self.row_number, "reason": self.reason}


@dataclass(frozen=True)
class NewsReplayFixtureBuildResult:
    """Summary for a news replay fixture build."""

    ok: bool
    input_path: Path
    output_path: Path
    input_rows: int
    output_rows: int
    invalid_rows: int
    tickers: tuple[str, ...]
    skipped: tuple[InvalidNewsRow, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "input_path": str(self.input_path),
            "output_path": str(self.output_path),
            "input_rows": self.input_rows,
            "output_rows": self.output_rows,
            "invalid_rows": self.invalid_rows,
            "tickers": list(self.tickers),
            "skipped": [row.to_dict() for row in self.skipped],
        }


def build_news_replay_fixture(
    input_path: str | Path,
    output_path: str | Path,
    *,
    skip_invalid: bool = False,
) -> NewsReplayFixtureBuildResult:
    """Build a JSONL fixture compatible with ``FileReplayNewsProvider``."""
    source_path = Path(input_path)
    target_path = Path(output_path)
    raw_rows = _read_input_rows(source_path)
    canonical_rows: list[dict[str, Any]] = []
    invalid_rows: list[InvalidNewsRow] = []

    for input_row in raw_rows:
        try:
            canonical_rows.append(_normalize_row(input_row))
        except NewsReplayFixtureBuildError as exc:
            invalid = InvalidNewsRow(row_number=input_row.row_number, reason=str(exc))
            if not skip_invalid:
                raise NewsReplayFixtureBuildError(
                    f"invalid news row {invalid.row_number}: {invalid.reason}"
                ) from exc
            invalid_rows.append(invalid)

    if not canonical_rows:
        raise NewsReplayFixtureBuildError("no valid news rows to write")

    canonical_rows.sort(key=_sort_key)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in canonical_rows) + "\n",
        encoding="utf-8",
    )

    try:
        FileReplayNewsProvider(target_path)
    except Exception as exc:
        raise NewsReplayFixtureBuildError(f"generated replay fixture failed validation: {exc}") from exc

    return NewsReplayFixtureBuildResult(
        ok=True,
        input_path=source_path,
        output_path=target_path,
        input_rows=len(raw_rows),
        output_rows=len(canonical_rows),
        invalid_rows=len(invalid_rows),
        tickers=tuple(sorted({str(row["ticker"]) for row in canonical_rows})),
        skipped=tuple(invalid_rows),
    )


@dataclass(frozen=True)
class _InputRow:
    row_number: int
    payload: Mapping[str, Any]
    ticker_hint: str | None = None


def _read_input_rows(path: Path) -> list[_InputRow]:
    if not path.exists():
        raise NewsReplayFixtureBuildError(f"input file not found: {path}")
    if not path.is_file():
        raise NewsReplayFixtureBuildError(f"input path is not a file: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        return _read_json_rows(path)
    if suffix == ".jsonl":
        return _read_jsonl_rows(path)
    if suffix == ".csv":
        return _read_csv_rows(path)
    raise NewsReplayFixtureBuildError(f"unsupported input format: {path.suffix or '<none>'}")


def _read_json_rows(path: Path) -> list[_InputRow]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NewsReplayFixtureBuildError(f"invalid JSON input: {path}") from exc
    except OSError as exc:
        raise NewsReplayFixtureBuildError(f"input file is not readable: {path}") from exc

    rows = list(_iter_json_payload_rows(payload))
    if not rows:
        raise NewsReplayFixtureBuildError("JSON input contains no news rows")
    return rows


def _iter_json_payload_rows(payload: Any) -> Iterable[_InputRow]:
    if isinstance(payload, list):
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, Mapping):
                raise NewsReplayFixtureBuildError(f"JSON item {index} must be an object")
            yield _InputRow(index, dict(item))
        return

    if not isinstance(payload, Mapping):
        raise NewsReplayFixtureBuildError("JSON input must be an object or array")

    for field_name in COLLECTION_FIELDS:
        collection = payload.get(field_name)
        if isinstance(collection, list):
            for index, item in enumerate(collection, start=1):
                if not isinstance(item, Mapping):
                    raise NewsReplayFixtureBuildError(f"JSON {field_name} item {index} must be an object")
                yield _InputRow(index, dict(item))
            return

    row_number = 1
    for ticker, rows in payload.items():
        if not isinstance(rows, list):
            raise NewsReplayFixtureBuildError(f"ticker-keyed JSON value for {ticker} must be a list")
        for item in rows:
            if not isinstance(item, Mapping):
                raise NewsReplayFixtureBuildError(f"ticker-keyed JSON row for {ticker} must be an object")
            yield _InputRow(row_number, dict(item), ticker_hint=str(ticker))
            row_number += 1


def _read_jsonl_rows(path: Path) -> list[_InputRow]:
    rows: list[_InputRow] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise NewsReplayFixtureBuildError(f"input file is not readable: {path}") from exc

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise NewsReplayFixtureBuildError(f"invalid JSONL on line {line_number}: {path}") from exc
        if not isinstance(payload, Mapping):
            raise NewsReplayFixtureBuildError(f"JSONL line {line_number} must be an object")
        rows.append(_InputRow(line_number, dict(payload)))

    if not rows:
        raise NewsReplayFixtureBuildError("JSONL input contains no news rows")
    return rows


def _read_csv_rows(path: Path) -> list[_InputRow]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [
                _InputRow(index, _drop_empty_values(row))
                for index, row in enumerate(csv.DictReader(handle), start=2)
            ]
    except OSError as exc:
        raise NewsReplayFixtureBuildError(f"input file is not readable: {path}") from exc

    if not rows:
        raise NewsReplayFixtureBuildError("CSV input contains no news rows")
    return rows


def _normalize_row(input_row: _InputRow) -> dict[str, Any]:
    row = dict(input_row.payload)
    ticker = _string_field(row, TICKER_FIELDS) or input_row.ticker_hint
    title = _string_field(row, TITLE_FIELDS)
    publish_time = _publish_time_field(row)

    if not ticker or not str(ticker).strip():
        raise NewsReplayFixtureBuildError("missing ticker")
    if not title:
        raise NewsReplayFixtureBuildError("missing title")
    if not publish_time:
        raise NewsReplayFixtureBuildError("missing or invalid publish_time")

    normalized: dict[str, Any] = {
        "ticker": str(ticker).strip().upper(),
        "title": title,
        "publish_time": publish_time,
    }
    publisher = _string_field(row, PUBLISHER_FIELDS)
    if publisher:
        normalized["publisher"] = publisher
    url = _string_field(row, URL_FIELDS)
    if url:
        normalized["url"] = url
    summary = _string_field(row, SUMMARY_FIELDS)
    if summary:
        normalized["summary"] = summary

    for key, value in row.items():
        if key in ALIAS_FIELDS or key in CANONICAL_FIELDS:
            continue
        if key in normalized:
            continue
        safe_value = _json_safe(value)
        if safe_value is not None:
            normalized[str(key)] = safe_value
    return normalized


def _string_field(row: Mapping[str, Any], fields: tuple[str, ...]) -> str | None:
    for field_name in fields:
        value = row.get(field_name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _publish_time_field(row: Mapping[str, Any]) -> str | None:
    raw_value: Any = None
    for field_name in PUBLISH_TIME_FIELDS:
        value = row.get(field_name)
        if value is not None and str(value).strip():
            raw_value = value
            break
    if raw_value is None:
        return None

    parsed = pd.to_datetime(raw_value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).isoformat().replace("+00:00", "Z")


def _sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("ticker", "")),
        str(row.get("publish_time", "")),
        str(row.get("title", "")),
    )


def _drop_empty_values(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in {None, ""}}


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            safe_item = _json_safe(item)
            if safe_item is not None:
                result[str(key)] = safe_item
        return result
    if isinstance(value, (list, tuple)):
        result_list = []
        for item in value:
            safe_item = _json_safe(item)
            if safe_item is not None:
                result_list.append(safe_item)
        return result_list
    return str(value)
