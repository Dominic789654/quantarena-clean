"""Read-only cache health reporting for QuantArena workflows."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from backtest.benchmark_cache import BenchmarkPriceCache


FIXED_BACKTEST_TICKERS = ("AAPL", "MSFT", "NVDA")
FIXED_BACKTEST_BENCHMARK_INDEX = "^GSPC"
FIXED_BACKTEST_START_DATE = "2026-06-01"
FIXED_BACKTEST_END_DATE = "2026-06-05"
DEFAULT_DB_PATH = Path("data/signal_flux.db")
DEFAULT_BENCHMARK_CACHE_DIR = Path("tests/fixtures/fixed_backtest_data/benchmark_cache")
DEFAULT_NEWS_REPLAY_PATH = Path("tests/fixtures/fixed_backtest_data/news_replay.jsonl")
DEFAULT_SHARED_PHASE1_CACHE_DIR = Path("data/backtest/shared_phase1_artifacts")
DEFAULT_SHARED_ANALYST_CACHE_DIR = Path("data/backtest/shared_analyst_cache")


@dataclass(frozen=True)
class CacheHealthFinding:
    """One cache health problem."""

    layer: str
    key: str
    reason: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "key": self.key,
            "reason": self.reason,
            "path": self.path,
        }


@dataclass(frozen=True)
class CacheHealthLayer:
    """Health details for one cache layer."""

    name: str
    status: str
    required: bool
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "required": self.required,
            "path": self.path,
            "details": self.details,
        }


@dataclass(frozen=True)
class CacheHealthReport:
    """Read-only cache health report."""

    ok: bool
    profile: str
    layers: tuple[CacheHealthLayer, ...]
    findings: tuple[CacheHealthFinding, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "profile": self.profile,
            "layers": [layer.to_dict() for layer in self.layers],
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class FixedBacktestCacheHealthConfig:
    """Inputs for the fixed-backtest cache health profile."""

    db_path: Path = DEFAULT_DB_PATH
    benchmark_cache_dir: Path = DEFAULT_BENCHMARK_CACHE_DIR
    news_replay_path: Path = DEFAULT_NEWS_REPLAY_PATH
    shared_phase1_cache_dir: Path = DEFAULT_SHARED_PHASE1_CACHE_DIR
    shared_analyst_cache_dir: Path = DEFAULT_SHARED_ANALYST_CACHE_DIR
    tickers: tuple[str, ...] = FIXED_BACKTEST_TICKERS
    benchmark_index: str = FIXED_BACKTEST_BENCHMARK_INDEX
    start_date: str = FIXED_BACKTEST_START_DATE
    end_date: str = FIXED_BACKTEST_END_DATE


def build_parser() -> argparse.ArgumentParser:
    """Build the cache health CLI parser."""
    parser = argparse.ArgumentParser(
        prog="run_cache_health.py",
        description="Report QuantArena cache readiness without fetching live data.",
    )
    parser.add_argument(
        "--profile",
        choices=["fixed-backtest"],
        default="fixed-backtest",
        help="Cache health profile to evaluate",
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--benchmark-cache-dir", type=Path, default=DEFAULT_BENCHMARK_CACHE_DIR)
    parser.add_argument("--news-replay-fixture", type=Path, default=DEFAULT_NEWS_REPLAY_PATH)
    parser.add_argument("--shared-phase1-cache-dir", type=Path, default=DEFAULT_SHARED_PHASE1_CACHE_DIR)
    parser.add_argument("--shared-analyst-cache-dir", type=Path, default=DEFAULT_SHARED_ANALYST_CACHE_DIR)
    parser.add_argument("--json", action="store_true", help="Print machine-readable report output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when required cache health checks fail",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run cache health from CLI arguments."""
    parser = build_parser()
    args = parser.parse_args(argv)
    report = run_fixed_backtest_cache_health(
        FixedBacktestCacheHealthConfig(
            db_path=args.db_path,
            benchmark_cache_dir=args.benchmark_cache_dir,
            news_replay_path=args.news_replay_fixture,
            shared_phase1_cache_dir=args.shared_phase1_cache_dir,
            shared_analyst_cache_dir=args.shared_analyst_cache_dir,
        )
    )
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True))
    else:
        _print_human_report(report)
    return 0 if report.ok or not args.strict else 1


def run_fixed_backtest_cache_health(
    config: FixedBacktestCacheHealthConfig | None = None,
) -> CacheHealthReport:
    """Inspect cache readiness for the fixed one-week backtest profile."""
    effective_config = config or FixedBacktestCacheHealthConfig()
    trading_days = _date_range(effective_config.start_date, effective_config.end_date)
    layers = [
        _check_stock_price_cache(effective_config, trading_days),
        _check_benchmark_cache(effective_config, trading_days),
        _check_news_replay_fixture(effective_config, trading_days),
        _check_directory_cache(
            name="shared_phase1_cache",
            path=effective_config.shared_phase1_cache_dir,
            required=False,
        ),
        _check_directory_cache(
            name="shared_analyst_cache",
            path=effective_config.shared_analyst_cache_dir,
            required=False,
        ),
    ]
    findings = tuple(_findings_from_layers(layers))
    return CacheHealthReport(
        ok=not any(finding for finding in findings if _finding_is_required(finding, layers)),
        profile="fixed-backtest",
        layers=tuple(layers),
        findings=findings,
    )


def _check_stock_price_cache(
    config: FixedBacktestCacheHealthConfig,
    trading_days: list[str],
) -> CacheHealthLayer:
    details: dict[str, Any] = {
        "tickers": {},
        "start_date": config.start_date,
        "end_date": config.end_date,
        "required_rows": len(trading_days),
    }
    if not config.db_path.is_file():
        return CacheHealthLayer(
            name="stock_price_db",
            status="miss",
            required=True,
            path=str(config.db_path),
            details={**details, "reason": "database_missing"},
        )

    try:
        connection = sqlite3.connect(f"file:{config.db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return CacheHealthLayer(
            name="stock_price_db",
            status="miss",
            required=True,
            path=str(config.db_path),
            details={**details, "reason": f"database_unreadable: {exc}"},
        )

    missing: list[str] = []
    try:
        for ticker in config.tickers:
            dates = _stock_price_dates(connection, ticker, config.start_date, config.end_date)
            missing_dates = [day for day in trading_days if day not in dates]
            details["tickers"][ticker] = {
                "rows": len(dates),
                "missing_dates": missing_dates,
                "status": "hit" if not missing_dates else "miss",
            }
            if missing_dates:
                missing.append(ticker)
    finally:
        connection.close()

    return CacheHealthLayer(
        name="stock_price_db",
        status="hit" if not missing else "miss",
        required=True,
        path=str(config.db_path),
        details=details,
    )


def _stock_price_dates(
    connection: sqlite3.Connection,
    ticker: str,
    start_date: str,
    end_date: str,
) -> set[str]:
    try:
        rows = connection.execute(
            """
            SELECT date FROM stock_prices
            WHERE ticker = ? AND date >= ? AND date <= ?
            ORDER BY date
            """,
            (ticker, start_date, end_date),
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0])[:10] for row in rows}


def _check_benchmark_cache(
    config: FixedBacktestCacheHealthConfig,
    trading_days: list[str],
) -> CacheHealthLayer:
    cache = BenchmarkPriceCache(cache_dir=config.benchmark_cache_dir, enabled=True)
    path = cache.path_for(config.benchmark_index)
    series = cache.load_covering(config.benchmark_index, trading_days)
    details = {
        "index_code": config.benchmark_index,
        "required_rows": len(trading_days),
        "rows": int(len(series)),
        "start_date": config.start_date,
        "end_date": config.end_date,
    }
    if series.empty:
        details["reason"] = "benchmark_cache_missing_or_incomplete"
    return CacheHealthLayer(
        name="benchmark_price_cache",
        status="hit" if not series.empty else "miss",
        required=True,
        path=str(path),
        details=details,
    )


def _check_news_replay_fixture(
    config: FixedBacktestCacheHealthConfig,
    trading_days: list[str],
) -> CacheHealthLayer:
    details: dict[str, Any] = {
        "tickers": list(config.tickers),
        "start_date": config.start_date,
        "end_date": config.end_date,
        "rows": 0,
        "matching_rows": 0,
    }
    if not config.news_replay_path.is_file():
        return CacheHealthLayer(
            name="news_replay_fixture",
            status="miss",
            required=True,
            path=str(config.news_replay_path),
            details={**details, "reason": "fixture_missing"},
        )
    rows, invalid_rows, matching_rows = _scan_news_replay_fixture(
        config.news_replay_path,
        tickers=set(config.tickers),
        trading_days=set(trading_days),
    )
    details.update({"rows": rows, "invalid_rows": invalid_rows, "matching_rows": matching_rows})
    if rows == 0:
        details["reason"] = "fixture_empty"
    elif invalid_rows:
        details["reason"] = "fixture_has_invalid_rows"
    elif matching_rows == 0:
        details["reason"] = "fixture_no_matching_rows"
    return CacheHealthLayer(
        name="news_replay_fixture",
        status="hit" if rows > 0 and invalid_rows == 0 and matching_rows > 0 else "miss",
        required=True,
        path=str(config.news_replay_path),
        details=details,
    )


def _scan_news_replay_fixture(
    path: Path,
    *,
    tickers: set[str],
    trading_days: set[str],
) -> tuple[int, int, int]:
    rows = 0
    invalid_rows = 0
    matching_rows = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_rows += 1
            continue
        if not isinstance(payload, Mapping):
            invalid_rows += 1
            continue
        rows += 1
        ticker = str(payload.get("ticker") or payload.get("symbol") or "").upper()
        publish_time = str(payload.get("publish_time") or payload.get("date") or "")
        publish_date = publish_time[:10]
        if ticker in tickers or publish_date in trading_days:
            matching_rows += 1
    return rows, invalid_rows, matching_rows


def _check_directory_cache(*, name: str, path: Path, required: bool) -> CacheHealthLayer:
    exists = path.exists()
    file_count = 0
    if exists and path.is_dir():
        file_count = sum(1 for item in path.rglob("*") if item.is_file())
    return CacheHealthLayer(
        name=name,
        status="hit" if exists else "missing_optional",
        required=required,
        path=str(path),
        details={"exists": exists, "file_count": file_count},
    )


def _findings_from_layers(layers: Sequence[CacheHealthLayer]) -> list[CacheHealthFinding]:
    findings: list[CacheHealthFinding] = []
    for layer in layers:
        if layer.status == "hit" or (not layer.required and layer.status == "missing_optional"):
            continue
        findings.append(
            CacheHealthFinding(
                layer=layer.name,
                key=str(layer.details.get("index_code") or layer.details.get("tickers") or layer.name),
                reason=str(layer.details.get("reason") or layer.status),
                path=layer.path,
            )
        )
    return findings


def _finding_is_required(finding: CacheHealthFinding, layers: Sequence[CacheHealthLayer]) -> bool:
    return any(layer.name == finding.layer and layer.required for layer in layers)


def _date_range(start_date: str, end_date: str) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _print_human_report(report: CacheHealthReport) -> None:
    print("QuantArena cache health")
    print(f"profile: {report.profile}")
    print(f"ok: {report.ok}")
    for layer in report.layers:
        required = "required" if layer.required else "optional"
        print(f"- {layer.name}: {layer.status} ({required})")
        if layer.path:
            print(f"  path: {layer.path}")
    for finding in report.findings:
        print(f"finding: {finding.layer} {finding.key}: {finding.reason}")


if __name__ == "__main__":
    raise SystemExit(main())
