"""File-backed benchmark close-price cache for deterministic backtests."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class BenchmarkPriceCache:
    """JSONL cache for benchmark daily close prices."""

    cache_dir: Path | str | None = None
    enabled: bool | None = None

    def __post_init__(self) -> None:
        raw_dir = self.cache_dir or os.getenv("BENCHMARK_CACHE_DIR", "data/benchmark_cache")
        raw_enabled = os.getenv("BENCHMARK_CACHE_ENABLED", "true").strip().lower()
        enabled = self.enabled if self.enabled is not None else raw_enabled not in {"0", "false", "no", "off"}
        object.__setattr__(self, "cache_dir", Path(raw_dir))
        object.__setattr__(self, "enabled", bool(enabled))

    def load_covering(self, index_code: str, trading_days: list[str]) -> pd.Series:
        """Return cached closes covering all requested trading days, or an empty series."""
        if not self.enabled or not trading_days:
            return pd.Series(dtype=float)
        path = self.path_for(index_code)
        if not path.exists():
            return pd.Series(dtype=float)

        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
        except (OSError, json.JSONDecodeError):
            return pd.Series(dtype=float)

        if not rows:
            return pd.Series(dtype=float)

        frame = pd.DataFrame(rows)
        if "date" not in frame.columns or "close" not in frame.columns:
            return pd.Series(dtype=float)

        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).sort_values("date")
        if frame.empty:
            return pd.Series(dtype=float)

        close_series = frame.drop_duplicates(subset=["date"], keep="last").set_index("date")["close"]
        target_index = pd.to_datetime(trading_days)
        aligned = close_series.reindex(target_index)
        if aligned.isna().any() or len(aligned) != len(target_index):
            return pd.Series(dtype=float)
        aligned.name = "close"
        aligned.index.name = "date"
        return aligned

    def save(self, index_code: str, close_series: pd.Series) -> Path | None:
        """Persist daily closes for an index code."""
        if not self.enabled or close_series is None or close_series.empty:
            return None

        cleaned = close_series.copy()
        cleaned.index = pd.to_datetime(cleaned.index, errors="coerce")
        cleaned = pd.to_numeric(cleaned, errors="coerce")
        cleaned = cleaned[cleaned.index.notna()]
        cleaned = cleaned.dropna().sort_index()
        if cleaned.empty:
            return None

        path = self.path_for(index_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for date, close in cleaned.items():
            lines.append(
                json.dumps(
                    {
                        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                        "close": float(close),
                    },
                    sort_keys=True,
                )
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def path_for(self, index_code: str) -> Path:
        return Path(self.cache_dir) / f"{_cache_key(index_code)}.jsonl"


def _cache_key(index_code: str) -> str:
    raw_key = str(index_code).strip().replace("^", "caret_")
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_key).strip("._-")
    return key or "benchmark"
