"""Shared phase1 artifact cache-aside pipeline for BacktestWorkflowAdapter.

Moved verbatim (behavior-preserving) from `BacktestWorkflowAdapter`
instance methods by the extract-workflow-phase1-pipeline change
(docs/refactor_program_plan.md Phase 3, step 21). Both functions below
read adapter instance state (`shared_phase1_artifact_cache`, `market`,
`tickers`, `analysts`, `llm_provider`, `llm_model`,
`SHARED_PHASE1_ARTIFACT_VERSION`) and call into delegators extracted in
earlier Phase 3 steps (`_build_phase1_prefetched_analyst_inputs`,
`_resolve_phase1_input_metadata`, `collect_signals_only_parallel_v2`,
`_get_smart_priority_order`). Following the adapter-passing convention
established by every prior Phase 3 step, each function takes the
adapter instance as its first parameter, named `adapter`, mirroring the
original `self` receiver.

`backtest/workflow_adapter.py` keeps same-named delegator *instance
methods* (not staticmethods) for both names, because
`load_or_compute_shared_phase1` must remain reachable through the MRO:
`tests/test_multi_personality_day_orchestrator.py` defines
`BacktestWorkflowAdapter` subclasses that override
`load_or_compute_shared_phase1` and call
`super().load_or_compute_shared_phase1(...)`. Every internal call from
one of these two functions to another, or to any adapter delegator,
goes through `adapter.<name>(...)`, never a direct module-level call.
"""

from datetime import UTC, datetime
from typing import Any, Dict, Optional

from loguru import logger

from backtest.workflow.phase1_artifact import SharedPhase1Artifact, SharedPhase1ArtifactCache


def _build_shared_phase1_artifact(
    adapter,
    trading_date: str,
    prices: Dict[str, float],
    enhanced_signals: Dict[str, Any],
    phase1_input_metadata: Optional[Dict[str, Any]] = None,
) -> SharedPhase1Artifact:
    phase1_input_metadata = dict(phase1_input_metadata or {})
    return SharedPhase1Artifact(
        trading_date=trading_date,
        prices=dict(prices),
        enhanced_signals=enhanced_signals,
        priority_order=adapter._get_smart_priority_order(enhanced_signals),
        metadata={
            "market": adapter.market,
            "tickers": list(adapter.tickers),
            "analysts": list(adapter.analysts),
            "llm_provider": adapter.llm_provider,
            "llm_model": adapter.llm_model,
            "generated_at": datetime.now(UTC).isoformat(),
            "artifact_version": adapter.SHARED_PHASE1_ARTIFACT_VERSION,
            "priority_score_version": SharedPhase1ArtifactCache.PRIORITY_SCORE_VERSION,
            "cache_hit": False,
            "price_input_signature": SharedPhase1ArtifactCache._prices_signature(prices),
            **phase1_input_metadata,
        },
    )


def load_or_compute_shared_phase1(
    adapter,
    trading_date: str,
    prices: Dict[str, float],
    max_workers: int = 5,
) -> SharedPhase1Artifact:
    artifact: Optional[SharedPhase1Artifact] = None
    phase1_input_metadata: Dict[str, Any] = {}
    prefetched_analyst_inputs: Dict[str, Dict[str, Any]] = {}
    shared_phase1_cache_enabled = adapter.shared_phase1_artifact_cache is not None

    if shared_phase1_cache_enabled:
        try:
            prefetched_analyst_inputs = adapter._build_phase1_prefetched_analyst_inputs(trading_date, prices)
            phase1_input_metadata = adapter._resolve_phase1_input_metadata(
                trading_date,
                prices,
                prefetched_analyst_inputs=prefetched_analyst_inputs,
            )
        except Exception as signature_error:
            shared_phase1_cache_enabled = False
            prefetched_analyst_inputs = {}
            logger.warning(
                f"Shared phase1 input signature resolution failed for {trading_date}; bypassing cache: {signature_error}"
            )

    if shared_phase1_cache_enabled:
        try:
            artifact = adapter.shared_phase1_artifact_cache.load(
                trading_date=trading_date,
                market=adapter.market,
                tickers=adapter.tickers,
                analysts=adapter.analysts,
                llm_provider=adapter.llm_provider,
                llm_model=adapter.llm_model,
                prices=prices,
                phase1_input_signature=str(phase1_input_metadata["phase1_input_signature"]),
            )
        except Exception as cache_error:
            logger.warning(f"Shared phase1 artifact cache load failed for {trading_date}: {cache_error}")
            artifact = None

    if artifact is not None:
        artifact.prices = dict(prices)
        artifact.metadata = {
            **artifact.metadata,
            **phase1_input_metadata,
            "resolved_at": datetime.now(UTC).isoformat(),
            "cache_hit": True,
        }
        return artifact

    if prefetched_analyst_inputs:
        enhanced_signals = adapter.collect_signals_only_parallel_v2(
            trading_date,
            prices,
            max_workers,
            prefetched_analyst_inputs=prefetched_analyst_inputs,
        )
    else:
        enhanced_signals = adapter.collect_signals_only_parallel_v2(
            trading_date,
            prices,
            max_workers,
        )
    artifact = adapter._build_shared_phase1_artifact(
        trading_date,
        prices,
        enhanced_signals,
        phase1_input_metadata=phase1_input_metadata,
    )

    if shared_phase1_cache_enabled:
        try:
            adapter.shared_phase1_artifact_cache.save(
                trading_date=trading_date,
                market=adapter.market,
                tickers=adapter.tickers,
                analysts=adapter.analysts,
                llm_provider=adapter.llm_provider,
                llm_model=adapter.llm_model,
                prices=prices,
                phase1_input_signature=str(phase1_input_metadata["phase1_input_signature"]),
                artifact=artifact,
            )
        except Exception as cache_error:
            logger.warning(f"Shared phase1 artifact cache save failed for {trading_date}: {cache_error}")

    return artifact
