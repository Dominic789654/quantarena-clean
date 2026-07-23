"""Company-news signature / cache-invalidation plumbing for
BacktestWorkflowAdapter's shared analyst-signal cache and shared
phase-1 artifact cache.

Moved (behavior-preserving) from `BacktestWorkflowAdapter`
instance/static methods by the
extract-workflow-company-news-signature-resolver change
(docs/refactor_program_plan.md Phase 3). Three of the eight functions
below (`_get_company_news_signature_payload`,
`_ensure_company_news_prefetched_payload`,
`_build_phase1_prefetched_analyst_inputs`,
`_resolve_analyst_input_signature`, `_resolve_phase1_input_metadata`)
read `self.market`, `self.api_source`, and/or `self.analysts` from the
original adapter instance. Rather than lift each individual attribute
into its own positional parameter (which would force every call site —
including `_process_single_ticker_for_signals_v2` in
`workflow_adapter.py` and the mutual calls between the functions below —
to thread three extra arguments through every hop), each function that
needs adapter state takes the adapter instance itself as its first
parameter, named `adapter`, mirroring the original `self` receiver.
The two purely-static helpers (`_stable_json_signature`,
`_normalize_news_item`) and the one pure staticmethod
(`_get_prefetched_analyst_payload`) keep their original no-adapter
signatures.

`backtest/workflow_adapter.py` keeps same-named delegator methods on
`BacktestWorkflowAdapter` for every name below. Critically, every call
from one of these functions to another goes through the *delegator*
(`adapter.<name>(...)`), never a direct
`company_news_signature.<name>(...)` module call — because
`tests/test_workflow_adapter_smart_priority.py` monkeypatches
`_get_company_news_signature_payload` as a **class attribute** on
`BacktestWorkflowAdapter` in three tests
(`test_shared_phase1_reuses_prefetched_company_news_payload_for_execution`,
`test_shared_analyst_cache_invalidates_company_news_on_input_signature_change`,
`test_shared_phase1_artifact_news_change_invalidates`). Those tests
exercise the patch indirectly, through
`_process_single_ticker_for_signals_v2` -> `_resolve_analyst_input_signature`
-> `_ensure_company_news_prefetched_payload` -> `_get_company_news_signature_payload`,
and through `load_or_compute_shared_phase1` ->
`_build_phase1_prefetched_analyst_inputs` /
`_resolve_phase1_input_metadata` -> `_ensure_company_news_prefetched_payload`
-> `_get_company_news_signature_payload`. If any hop in either chain
called the module-level bare function instead of `adapter.<name>(...)`,
the monkeypatch would stop propagating past that hop and these tests
would silently stop testing the real cache-invalidation path (this was
verified experimentally while implementing this change: temporarily
routing `_ensure_company_news_prefetched_payload`'s internal call
through the bare module function made
`test_shared_analyst_cache_invalidates_company_news_on_input_signature_change`
fail).
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

from backtest.workflow.phase1_artifact import SharedPhase1ArtifactCache


def _stable_json_signature(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _normalize_news_item(news_item: Any) -> Dict[str, Any]:
    if hasattr(news_item, "model_dump"):
        payload = news_item.model_dump()
    elif isinstance(news_item, dict):
        payload = dict(news_item)
    else:
        payload = {
            "title": getattr(news_item, "title", None),
            "publish_time": getattr(news_item, "publish_time", None),
            "publisher": getattr(news_item, "publisher", None),
            "link": getattr(news_item, "link", None),
            "summary": getattr(news_item, "summary", None),
        }
    return {
        "title": payload.get("title"),
        "publish_time": payload.get("publish_time"),
        "publisher": payload.get("publisher"),
        "link": payload.get("link"),
        "summary": payload.get("summary"),
    }


def _get_company_news_signature_payload(adapter: Any, trading_date: str, ticker: str) -> Dict[str, Any]:
    from apis.router import Router, resolve_api_source
    from util.threshold_config import get_threshold_config

    trading_date_dt = datetime.strptime(trading_date, "%Y-%m-%d")
    news_count = int(get_threshold_config().get_thresholds("company_news").get("news_count", 10))
    api_source = resolve_api_source(adapter.market, adapter.api_source)
    router = Router(api_source)
    if adapter.market == "cn":
        news_items = router.get_cn_stock_news(ticker, trading_date_dt, news_count)
    else:
        news_items = router.get_us_stock_news(ticker, trading_date_dt, news_count)

    prompt_data = [
        item.model_dump_json() if hasattr(item, "model_dump_json") else json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in (news_items or [])
    ]
    normalized_items = [
        adapter._normalize_news_item(item)
        for item in (news_items or [])
    ]
    payload = {
        "ticker": ticker,
        "trading_date": trading_date,
        "count": len(normalized_items),
        "items": normalized_items,
        "prompt_data": prompt_data,
        "signature": adapter._stable_json_signature(prompt_data),
    }
    return payload


def _get_prefetched_analyst_payload(
    prefetched_analyst_data: Optional[Dict[str, Any]],
    analyst_key: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(prefetched_analyst_data, dict):
        return None
    payload = prefetched_analyst_data.get(analyst_key)
    return payload if isinstance(payload, dict) else None


def _ensure_company_news_prefetched_payload(
    adapter: Any,
    trading_date: str,
    ticker: str,
    prefetched_analyst_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = adapter._get_prefetched_analyst_payload(prefetched_analyst_data, "company_news")
    if payload is None:
        payload = adapter._get_company_news_signature_payload(trading_date, ticker)
        if isinstance(prefetched_analyst_data, dict):
            prefetched_analyst_data["company_news"] = payload
    return payload


def _build_phase1_prefetched_analyst_inputs(
    adapter: Any,
    trading_date: str,
    prices: Dict[str, float],
) -> Dict[str, Dict[str, Any]]:
    prefetched_inputs: Dict[str, Dict[str, Any]] = {}
    if "company_news" not in adapter.analysts:
        return prefetched_inputs
    for ticker in sorted(prices):
        prefetched_inputs.setdefault(ticker, {})["company_news"] = adapter._get_company_news_signature_payload(
            trading_date,
            ticker,
        )
    return prefetched_inputs


def _resolve_analyst_input_signature(
    adapter: Any,
    trading_date: str,
    ticker: str,
    analyst_key: str,
    prefetched_analyst_data: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    if analyst_key == "company_news":
        payload = adapter._ensure_company_news_prefetched_payload(
            trading_date,
            ticker,
            prefetched_analyst_data,
        )
        return str(payload["signature"])
    return None


def _resolve_phase1_input_metadata(
    adapter: Any,
    trading_date: str,
    prices: Dict[str, float],
    prefetched_analyst_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    prices_signature = SharedPhase1ArtifactCache._prices_signature(prices)
    tickers_signature = SharedPhase1ArtifactCache._signature(sorted(prices.keys()))
    metadata: Dict[str, Any] = {
        "price_input_signature": prices_signature,
        "tickers_input_signature": tickers_signature,
    }
    component_signatures: Dict[str, Any] = {
        "prices": prices_signature,
        "tickers": tickers_signature,
    }

    if "company_news" in adapter.analysts:
        news_by_ticker: Dict[str, str] = {}
        prefetched_analyst_inputs = prefetched_analyst_inputs or {}
        for ticker in sorted(prices):
            payload = adapter._ensure_company_news_prefetched_payload(
                trading_date,
                ticker,
                prefetched_analyst_inputs.setdefault(ticker, {}),
            )
            news_by_ticker[ticker] = str(payload["signature"])
        news_signature = adapter._stable_json_signature(news_by_ticker)
        metadata["news_input_signature"] = news_signature
        metadata["news_input_signatures_by_ticker"] = news_by_ticker
        component_signatures["company_news"] = news_signature

    phase1_input_signature = adapter._stable_json_signature(component_signatures)
    metadata["phase1_input_signature"] = phase1_input_signature
    return metadata
