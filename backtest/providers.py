"""Provider interfaces and replay implementations for backtest market data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import pandas as pd

from quantarena.news_diagnostics import classify_zero_reason, record_news_diagnostic


class ProviderDataError(RuntimeError):
    """Raised when a provider cannot supply requested offline or live data."""


@dataclass(frozen=True)
class ProviderFailure:
    """Structured provider failure record for logging and tests."""

    provider: str
    operation: str
    error_type: str
    message: str
    ticker: str | None = None
    market: str | None = None
    date: str | None = None

    @classmethod
    def from_exception(
        cls,
        *,
        provider: str,
        operation: str,
        exc: Exception,
        ticker: str | None = None,
        market: str | None = None,
        date: str | None = None,
    ) -> "ProviderFailure":
        return cls(
            provider=str(provider),
            operation=operation,
            error_type=type(exc).__name__,
            message=_redact_provider_message(str(exc)),
            ticker=ticker,
            market=market,
            date=date,
        )

    def summary(self) -> str:
        context = []
        if self.market:
            context.append(f"market={self.market}")
        if self.ticker:
            context.append(f"ticker={self.ticker}")
        if self.date:
            context.append(f"date={self.date}")
        context_text = " ".join(context)
        prefix = f"provider={self.provider} operation={self.operation}"
        if context_text:
            prefix = f"{prefix} {context_text}"
        return f"{prefix} error={self.error_type}: {self.message}"


class DailyCandleProvider(Protocol):
    """Interface for providers that return daily OHLCV candles."""

    name: str

    def get_daily_candles(self, ticker: str, end_date: datetime) -> pd.DataFrame:
        """Return candles for ``ticker`` up to and including ``end_date``."""


class NewsProvider(Protocol):
    """Interface for providers that return company news items."""

    name: str

    def get_news(self, ticker: str, trading_date: datetime, limit: int, market: str) -> list[Any]:
        """Return news items for ``ticker`` up to ``trading_date``."""


class FundamentalsProvider(Protocol):
    """Interface for providers that return company fundamentals."""

    name: str

    def get_fundamentals(self, ticker: str, market: str) -> Any:
        """Return fundamentals for ``ticker`` in ``market``."""


class MacroProvider(Protocol):
    """Interface for providers that return macroeconomic indicators."""

    name: str

    def get_economic_indicators(self, market: str) -> Any:
        """Return economic indicators for ``market``."""


@dataclass(frozen=True)
class ReplayDailyCandleProvider:
    """In-memory daily-candle provider for offline tests and reproduction checks."""

    frames: Mapping[str, pd.DataFrame]
    name: str = "replay"

    def get_daily_candles(self, ticker: str, end_date: datetime) -> pd.DataFrame:
        if ticker not in self.frames:
            raise ProviderDataError(f"Replay candles missing for {ticker}")

        frame = self.frames[ticker].copy()
        if frame.empty:
            return frame

        dated = _with_datetime_index(frame)
        return dated[dated.index <= end_date].copy()


@dataclass(frozen=True)
class ReplayNewsProvider:
    """In-memory company-news provider for offline tests and reproduction checks."""

    items: Mapping[str, Sequence[Any]]
    name: str = "replay_news"

    def get_news(self, ticker: str, trading_date: datetime, limit: int, market: str) -> list[Any]:
        if ticker not in self.items:
            raise ProviderDataError(f"Replay news missing for {ticker}")

        cutoff = _as_naive_utc(trading_date)
        filtered = [
            item
            for item in self.items[ticker]
            if _news_within_trading_date(item, cutoff)
        ]
        filtered.sort(key=_news_publish_time, reverse=True)
        return list(filtered[:limit])


@dataclass(frozen=True)
class FileReplayNewsProvider:
    """File-backed company-news provider for deterministic historical replay."""

    path: str | Path
    name: str = "replay_news"

    def __post_init__(self) -> None:
        fixture_path = Path(self.path)
        try:
            items = _load_replay_news_fixture(fixture_path)
        except ProviderDataError:
            raise
        except Exception as exc:
            raise ProviderDataError(f"Replay news fixture could not be loaded: {fixture_path}") from exc

        object.__setattr__(self, "_path", fixture_path)
        object.__setattr__(self, "_items", items)

    def get_news(self, ticker: str, trading_date: datetime, limit: int, market: str) -> list[Any]:
        ticker_key = _normalize_ticker(ticker)
        if ticker_key not in self._items:
            raise ProviderDataError(f"Replay news missing for {ticker}")

        cutoff = _as_naive_utc(trading_date)
        raw_items = list(self._items[ticker_key])
        filtered = [
            item
            for item in raw_items
            if _news_within_trading_date(item, cutoff)
        ]
        filtered.sort(key=_news_publish_time, reverse=True)
        limited = list(filtered[:limit])
        _record_replay_news_diagnostic(
            provider=self.name,
            ticker=ticker,
            trading_date=trading_date,
            limit=limit,
            market=market,
            raw_count=len(raw_items),
            date_filtered_count=len(filtered),
            final_count=len(limited),
        )
        return limited


@dataclass(frozen=True)
class ReplayFundamentalsProvider:
    """In-memory fundamentals provider for offline tests and reproduction checks."""

    fundamentals: Mapping[str, Any]
    name: str = "replay_fundamentals"

    def get_fundamentals(self, ticker: str, market: str) -> Any:
        if ticker not in self.fundamentals:
            raise ProviderDataError(f"Replay fundamentals missing for {ticker}")
        payload = self.fundamentals[ticker]
        if hasattr(payload, "model_dump_json"):
            return payload
        if isinstance(payload, Mapping):
            return _ReplayFundamentalsPayload(payload)
        raise ProviderDataError(
            f"Replay fundamentals for {ticker} must be a mapping or expose model_dump_json()"
        )


@dataclass(frozen=True)
class _ReplayFundamentalsPayload:
    payload: Mapping[str, Any]

    def model_dump_json(self) -> str:
        return json.dumps(self.payload, sort_keys=True)


@dataclass(frozen=True)
class ReplayMacroProvider:
    """In-memory macro indicator provider for offline tests and reproduction checks."""

    indicators: Any
    name: str = "replay_macro"

    def get_economic_indicators(self, market: str) -> Any:
        if hasattr(self.indicators, "__dict__") and not isinstance(self.indicators, Mapping):
            return self.indicators
        if isinstance(self.indicators, Mapping):
            return _ReplayMacroPayload(self.indicators)
        raise ProviderDataError("Replay macro indicators must be a mapping or attribute object")


@dataclass(frozen=True)
class _ReplayMacroPayload:
    payload: Mapping[str, Any]

    def __getattr__(self, name: str) -> Any:
        try:
            return self.payload[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _with_datetime_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy indexed by datetime using an existing index or date column."""
    dated = frame.copy()
    date_column = "date" if "date" in dated.columns else "Date" if "Date" in dated.columns else None
    if date_column:
        dated.index = pd.to_datetime(dated[date_column], errors="coerce")
        dated = dated.drop(columns=[date_column])
    else:
        dated.index = pd.to_datetime(dated.index, errors="coerce")

    dated = dated[dated.index.notna()]
    dated.index.name = "Date"
    return dated.sort_index()


def _load_replay_news_fixture(path: Path) -> dict[str, list[Any]]:
    if not path.exists():
        raise ProviderDataError(f"Replay news fixture not found: {path}")
    if not path.is_file():
        raise ProviderDataError(f"Replay news fixture is not a file: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProviderDataError(f"Replay news fixture is not readable: {path}") from exc

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return _load_replay_news_jsonl(text, path)
    if suffix == ".json":
        return _load_replay_news_json(text, path)
    raise ProviderDataError(f"Replay news fixture must be JSON or JSONL: {path}")


def _load_replay_news_json(text: str, path: Path) -> dict[str, list[Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderDataError(f"Replay news fixture contains invalid JSON: {path}") from exc

    if not isinstance(payload, Mapping):
        raise ProviderDataError(f"Replay news JSON fixture must be ticker-keyed: {path}")

    items: dict[str, list[Any]] = {}
    for ticker, rows in payload.items():
        if not isinstance(rows, list):
            raise ProviderDataError(f"Replay news rows for {ticker} must be a list: {path}")
        items[_normalize_ticker(ticker)] = list(rows)
    return items


def _load_replay_news_jsonl(text: str, path: Path) -> dict[str, list[Any]]:
    items: dict[str, list[Any]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ProviderDataError(
                f"Replay news JSONL fixture has invalid JSON on line {line_number}: {path}"
            ) from exc
        if not isinstance(row, Mapping):
            raise ProviderDataError(
                f"Replay news JSONL row {line_number} must be an object: {path}"
            )
        ticker = row.get("ticker") or row.get("symbol")
        if not ticker:
            raise ProviderDataError(
                f"Replay news JSONL row {line_number} is missing ticker/symbol: {path}"
            )
        items.setdefault(_normalize_ticker(ticker), []).append(dict(row))
    return items


def _record_replay_news_diagnostic(
    *,
    provider: str,
    ticker: str,
    trading_date: datetime,
    limit: int,
    market: str,
    raw_count: int,
    date_filtered_count: int,
    final_count: int,
) -> None:
    record_news_diagnostic(
        {
            "provider": provider,
            "market": market,
            "ticker": ticker,
            "trading_date": trading_date.strftime("%Y-%m-%d") if hasattr(trading_date, "strftime") else trading_date,
            "limit": limit,
            "raw_count": raw_count,
            "date_filtered_count": date_filtered_count,
            "final_count": final_count,
            "zero_reason": classify_zero_reason(
                raw_count=raw_count,
                date_filtered_count=date_filtered_count,
                final_count=final_count,
            ),
        }
    )


def _news_publish_time(item: Any) -> datetime:
    if isinstance(item, Mapping):
        raw_value = (
            item.get("publish_time")
            or item.get("published")
            or item.get("publishedDate")
            or item.get("published_date")
            or item.get("date")
            or ""
        )
    else:
        raw_value = getattr(item, "publish_time", "")

    if isinstance(raw_value, datetime):
        return _as_naive_utc(raw_value)
    if raw_value:
        parsed = pd.to_datetime(raw_value, errors="coerce")
        if pd.notna(parsed):
            return _as_naive_utc(parsed.to_pydatetime())
    return datetime.min


def _news_within_trading_date(item: Any, trading_date: datetime) -> bool:
    publish_time = _news_publish_time(item)
    if publish_time == datetime.min:
        return True
    return publish_time.date() <= trading_date.date()


def _normalize_ticker(ticker: Any) -> str:
    return str(ticker or "").strip().upper()


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _redact_provider_message(message: str) -> str:
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|apikey|access[_-]?token|token)(=)[^&\s]+",
        r"\1\2<redacted>",
        message,
    )
    redacted = re.sub(
        r"(?i)(['\"]?\b(?:api[_-]?key|apikey|access[_-]?token|token)\b['\"]?\s*:\s*['\"]?)[^'\"&,\s}]+",
        r"\1<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(\b(?:x-api-key|authorization)\b\s*:\s*['\"]?(?:bearer\s+)?)[^'\"&,\s}]+",
        r"\1<redacted>",
        redacted,
    )
    return redacted
