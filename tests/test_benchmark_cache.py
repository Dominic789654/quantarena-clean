"""Tests for file-backed benchmark price cache."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.benchmark_cache import BenchmarkPriceCache


def test_benchmark_price_cache_loads_covering_daily_closes(tmp_path: Path) -> None:
    cache = BenchmarkPriceCache(cache_dir=tmp_path)
    source = pd.Series(
        [100.0, 101.0, 102.0],
        index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
    )

    cache_path = cache.save("^GSPC", source)
    loaded = cache.load_covering("^GSPC", ["2026-06-01", "2026-06-02", "2026-06-03"])

    assert cache_path == tmp_path / "caret_GSPC.jsonl"
    assert list(loaded.index.strftime("%Y-%m-%d")) == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert loaded.tolist() == [100.0, 101.0, 102.0]


def test_benchmark_price_cache_rejects_partial_coverage(tmp_path: Path) -> None:
    cache = BenchmarkPriceCache(cache_dir=tmp_path)
    cache.save(
        "SPY",
        pd.Series(
            [100.0, 102.0],
            index=pd.to_datetime(["2026-06-01", "2026-06-03"]),
        ),
    )

    loaded = cache.load_covering("SPY", ["2026-06-01", "2026-06-02", "2026-06-03"])

    assert loaded.empty


def test_benchmark_price_cache_disabled_skips_reads_and_writes(tmp_path: Path) -> None:
    cache = BenchmarkPriceCache(cache_dir=tmp_path, enabled=False)

    cache_path = cache.save(
        "SPY",
        pd.Series([100.0], index=pd.to_datetime(["2026-06-01"])),
    )
    loaded = cache.load_covering("SPY", ["2026-06-01"])

    assert cache_path is None
    assert loaded.empty
    assert not list(tmp_path.iterdir())
