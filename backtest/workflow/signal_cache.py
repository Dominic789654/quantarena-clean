"""SharedAnalystSignalCache: best-effort file cache for analyst outputs
shared across personalities.

Moved verbatim (behavior-preserving) from backtest/workflow_adapter.py
by the extract-workflow-pure-dataclasses-and-caches change
(docs/refactor_program_plan.md Phase 3). backtest/workflow_adapter.py
re-imports this name so every existing `from backtest.workflow_adapter
import SharedAnalystSignalCache` import keeps resolving.
"""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, List, Optional


class SharedAnalystSignalCache:
    """Best-effort file cache for analyst outputs shared across personalities."""

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(
        self,
        trading_date: str,
        market: str,
        ticker: str,
        analyst_key: str,
        llm_provider: str,
        llm_model: str,
        input_signature: Optional[str] = None,
    ):
        from graph.schema import AnalystSignal

        path = self._entry_path(trading_date, market, ticker, analyst_key, llm_provider, llm_model, input_signature)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        items = payload.get("analyst_signals")
        if not isinstance(items, list):
            return None
        signals = []
        for item in items:
            try:
                signals.append(AnalystSignal.model_validate(item))
            except Exception:
                return None
        return signals

    def save(
        self,
        trading_date: str,
        market: str,
        ticker: str,
        analyst_key: str,
        llm_provider: str,
        llm_model: str,
        analyst_signals: List[Any],
        input_signature: Optional[str] = None,
    ) -> None:
        path = self._entry_path(trading_date, market, ticker, analyst_key, llm_provider, llm_model, input_signature)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now(UTC).isoformat(),
            "analyst_signals": [
                signal.model_dump() if hasattr(signal, "model_dump") else signal
                for signal in analyst_signals
            ],
        }
        tmp_path = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)

    @staticmethod
    def _safe_part(value: str) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
        cleaned = cleaned[:40] if cleaned else "item"
        return f"{cleaned}_{digest}"

    def _entry_path(
        self,
        trading_date: str,
        market: str,
        ticker: str,
        analyst_key: str,
        llm_provider: str,
        llm_model: str,
        input_signature: Optional[str] = None,
    ) -> Path:
        scope = self._safe_part(f"{analyst_key}_{llm_provider}_{llm_model}")
        if input_signature:
            scope = self._safe_part(f"{analyst_key}_{llm_provider}_{llm_model}_{input_signature}")
        return (
            self.cache_dir
            / self._safe_part(trading_date)
            / self._safe_part(market)
            / self._safe_part(ticker)
            / scope
        ).with_suffix(".json")
