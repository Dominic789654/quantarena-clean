"""SharedPhase1Artifact and SharedPhase1ArtifactCache: day-level shared
phase1 artifact reusable across personalities/runs, and its versioned
persistent file cache.

Moved verbatim (behavior-preserving) from backtest/workflow_adapter.py
by the extract-workflow-pure-dataclasses-and-caches change
(docs/refactor_program_plan.md Phase 3). backtest/workflow_adapter.py
re-imports these names so every existing `from backtest.workflow_adapter
import SharedPhase1Artifact` / `SharedPhase1ArtifactCache` import and
`monkeypatch.setattr("backtest.workflow_adapter.
SharedPhase1ArtifactCache.ARTIFACT_VERSION", ...)` string path keeps
resolving against the same class objects.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SharedPhase1Artifact:
    """Day-level shared phase1 artifact reusable across personalities and runs."""

    trading_date: str
    prices: Dict[str, float]
    enhanced_signals: Dict[str, Any]
    priority_order: List[str]
    metadata: Dict[str, Any]

    @staticmethod
    def _serialize_signal(signal: Any) -> Any:
        return signal.model_dump() if hasattr(signal, "model_dump") else signal

    @classmethod
    def _restore_signal(cls, signal: Any) -> Any:
        if not isinstance(signal, dict):
            return signal
        try:
            from graph.schema import AnalystSignal

            return AnalystSignal.model_validate(signal)
        except Exception:
            return signal

    @classmethod
    def _serialize_enhanced_signals(cls, enhanced_signals: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for ticker, item in (enhanced_signals or {}).items():
            item_dict = dict(item or {})
            signals = item_dict.get("analyst_signals")
            if isinstance(signals, list):
                item_dict["analyst_signals"] = [cls._serialize_signal(signal) for signal in signals]
            payload[ticker] = item_dict
        return payload

    @classmethod
    def _restore_enhanced_signals(cls, enhanced_signals: Dict[str, Any]) -> Dict[str, Any]:
        restored: Dict[str, Any] = {}
        for ticker, item in (enhanced_signals or {}).items():
            item_dict = dict(item or {})
            signals = item_dict.get("analyst_signals")
            if isinstance(signals, list):
                item_dict["analyst_signals"] = [cls._restore_signal(signal) for signal in signals]
            restored[ticker] = item_dict
        return restored

    def to_payload(self) -> Dict[str, Any]:
        return {
            "trading_date": self.trading_date,
            "prices": dict(self.prices or {}),
            "enhanced_signals": self._serialize_enhanced_signals(self.enhanced_signals),
            "priority_order": list(self.priority_order or []),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> Optional["SharedPhase1Artifact"]:
        if not isinstance(payload, dict):
            return None
        trading_date = payload.get("trading_date")
        prices = payload.get("prices")
        enhanced_signals = payload.get("enhanced_signals")
        priority_order = payload.get("priority_order")
        metadata = payload.get("metadata") or {}
        if not isinstance(trading_date, str):
            return None
        if not isinstance(prices, dict) or not isinstance(enhanced_signals, dict) or not isinstance(priority_order, list):
            return None
        return cls(
            trading_date=trading_date,
            prices=prices,
            enhanced_signals=cls._restore_enhanced_signals(enhanced_signals),
            priority_order=list(priority_order),
            metadata=dict(metadata),
        )


class SharedPhase1ArtifactCache:
    """Versioned persistent cache for shared day-level phase1 artifacts."""

    ARTIFACT_VERSION = "v2"
    PRIORITY_SCORE_VERSION = "v1"

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(
        self,
        trading_date: str,
        market: str,
        tickers: List[str],
        analysts: List[str],
        llm_provider: str,
        llm_model: str,
        prices: Dict[str, float],
        phase1_input_signature: str,
    ) -> Optional[SharedPhase1Artifact]:
        path = self._entry_path(
            trading_date,
            market,
            tickers,
            analysts,
            llm_provider,
            llm_model,
            prices,
            phase1_input_signature,
        )
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        artifact = SharedPhase1Artifact.from_payload(payload)
        if artifact is None:
            return None
        artifact.metadata = {
            **artifact.metadata,
            "cache_hit": True,
            "artifact_version": self.ARTIFACT_VERSION,
            "priority_score_version": self.PRIORITY_SCORE_VERSION,
        }
        return artifact

    def save(
        self,
        trading_date: str,
        market: str,
        tickers: List[str],
        analysts: List[str],
        llm_provider: str,
        llm_model: str,
        prices: Dict[str, float],
        phase1_input_signature: str,
        artifact: SharedPhase1Artifact,
    ) -> None:
        path = self._entry_path(
            trading_date,
            market,
            tickers,
            analysts,
            llm_provider,
            llm_model,
            prices,
            phase1_input_signature,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = artifact.to_payload()
        payload["metadata"] = {
            **dict(payload.get("metadata") or {}),
            "saved_at": datetime.now(UTC).isoformat(),
            "artifact_version": self.ARTIFACT_VERSION,
            "priority_score_version": self.PRIORITY_SCORE_VERSION,
            "cache_hit": False,
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

    @staticmethod
    def _signature(values: List[str]) -> str:
        raw = json.dumps(sorted(str(value) for value in values), ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _prices_signature(prices: Dict[str, float]) -> str:
        normalized = [
            [str(ticker), round(float(price), 8)]
            for ticker, price in sorted((prices or {}).items())
        ]
        raw = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _entry_path(
        self,
        trading_date: str,
        market: str,
        tickers: List[str],
        analysts: List[str],
        llm_provider: str,
        llm_model: str,
        prices: Dict[str, float],
        phase1_input_signature: str,
    ) -> Path:
        universe_sig = self._signature(tickers)
        analysts_sig = self._signature(analysts)
        prices_sig = self._prices_signature(prices)
        version_scope = self._safe_part(
            f"{llm_provider}_{llm_model}_{self.ARTIFACT_VERSION}_{self.PRIORITY_SCORE_VERSION}"
        )
        phase1_sig = self._safe_part(f"i_{phase1_input_signature}")
        return (
            self.cache_dir
            / self._safe_part(trading_date)
            / self._safe_part(market)
            / version_scope
            / self._safe_part(f"u_{universe_sig}")
            / self._safe_part(f"a_{analysts_sig}")
            / self._safe_part(f"p_{prices_sig}")
            / phase1_sig
        ).with_suffix(".json")
