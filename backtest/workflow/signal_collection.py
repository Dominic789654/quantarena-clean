"""The parallel analyst-signal collection engine for
BacktestWorkflowAdapter's smart-priority phase 1: collecting every
analyst's signal for every ticker (via a `ThreadPoolExecutor`, one
worker per ticker) before any portfolio decision is made.

Moved (behavior-preserving) from `BacktestWorkflowAdapter` instance
methods by the extract-workflow-signal-collection-engine change
(docs/refactor_program_plan.md Phase 3, step 20 — the highest-risk
step of the decomposition program). All six functions below read a
large amount of adapter instance state (`self.market`,
`self.api_source`, `self.personality`, `self.db_path`,
`self.shared_analyst_cache`, `self.tickers`, `self.exp_name`,
`self.current_portfolio`, `self.analysts`, `self.llm_provider`,
`self.llm_model`) and call several other delegator methods that
already live outside this module (`_resolve_analyst_input_signature`
in `backtest/workflow/company_news_signature.py`,
`_calculate_priority_score`/`_calculate_signal_consistency`/
`_signal_label`/`_aggregate_signal_from_summary`/`_get_smart_priority_order`
in `backtest/workflow/scoring.py`). Matching the pattern established by
`company_news_signature.py`, each function takes the adapter instance
itself as its first parameter, named `adapter`, and every call from one
of these six functions to another — or to any other adapter delegator
— goes through `adapter.<name>(...)`, never a direct module-level call.

This is not just the patch-propagation discipline carried over from the
previous step: `_process_single_ticker_for_signals_v2` runs inside
worker threads submitted by `collect_signals_only_parallel_v2`'s
`ThreadPoolExecutor`, and several tests
(`tests/test_multi_personality_day_orchestrator.py`,
`tests/test_fof_engine.py`) replace `collect_signals_only_parallel_v2`
with an instance-level `monkeypatch.setattr(adapter, ...)` or a
duck-typed fake adapter entirely — the thread-pool structure, the
`Lock`-guarded `signals` dict, and the `ImportError` fallback below are
preserved exactly (same lock scope, same exception handling at both the
per-future and whole-collection level) so those tests' expectations
about when/how many times signal collection happens keep holding.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional

from loguru import logger


def _process_single_ticker_for_signals_v2(
    adapter: Any,
    ticker: str,
    trading_date: str,
    trading_date_dt: datetime,
    price: float,
    config: Dict[str, Any],
    portfolio_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Process a single ticker to collect ALL analyst signals.
    Enhanced version for smart priority sorting.

    Returns:
        Enhanced signal dict with all analyst signals and metadata.
    """
    from agents.registry import AgentRegistry
    from graph.schema import FundState, Portfolio, Position, AnalystSignal
    from graph.constants import Signal

    # Create a copy of portfolio for this thread
    portfolio = Portfolio(
        id=portfolio_dict["id"],
        cashflow=portfolio_dict["cashflow"],
        positions={
            t: Position(
                shares=pos.get("shares", 0),
                value=pos.get("value", 0)
            )
            for t, pos in portfolio_dict["positions"].items()
        }
    )

    try:
        prefetched_analyst_data = dict(config.get("prefetched_analyst_inputs", {}).get(ticker, {}))
        state = FundState(
            ticker=ticker,
            exp_name=config["exp_name"],
            trading_date=trading_date_dt,
            market=adapter.market,
            api_source=adapter.api_source,
            llm_config=config["llm"],
            portfolio=portfolio,
            num_tickers=len(config["tickers"]),
            personality=adapter.personality,
            analyst_signals=[],
            decision=None,
            current_price=price,
            db_path=adapter.db_path,
            is_backtest=True,
            skip_db_writes=True,
            prefetched_analyst_data=prefetched_analyst_data,
        )

        workflow_analysts = config.get("workflow_analysts", [])
        valid_analysts = [a for a in workflow_analysts if AgentRegistry.check_agent_key(a)]
        invalid_analysts = [a for a in workflow_analysts if a not in valid_analysts]
        if invalid_analysts:
            logger.warning(f"Skipping invalid analysts for {ticker}: {invalid_analysts}")

        # Run analysts only and collect all emitted signals.
        analyst_signals: List[AnalystSignal] = []
        for analyst_key in valid_analysts:
            analyst_input_signature: Optional[str] = None
            try:
                analyst_input_signature = adapter._resolve_analyst_input_signature(
                    trading_date,
                    ticker,
                    analyst_key,
                    prefetched_analyst_data,
                )
            except Exception as signature_error:
                logger.warning(
                    f"Shared analyst input signature resolution failed for {analyst_key} {ticker} {trading_date}: {signature_error}"
                )

            cached_signals = adapter._load_shared_analyst_signals(
                trading_date=trading_date,
                ticker=ticker,
                analyst_key=analyst_key,
                llm_config=config["llm"],
                input_signature=analyst_input_signature,
            )
            if cached_signals is not None:
                analyst_signals.extend(cached_signals)
                continue

            analyst_func = AgentRegistry.get_agent_func_by_key(analyst_key)
            if analyst_func is None:
                logger.warning(f"Analyst function not found: {analyst_key}")
                continue

            try:
                result = analyst_func(state)
                new_signals = result.get("analyst_signals", [])
                analyst_signals.extend(new_signals)
                adapter._save_shared_analyst_signals(
                    trading_date=trading_date,
                    ticker=ticker,
                    analyst_key=analyst_key,
                    llm_config=config["llm"],
                    analyst_signals=new_signals,
                    input_signature=analyst_input_signature,
                )
            except Exception as analyst_error:
                logger.error(f"Analyst {analyst_key} failed for {ticker}: {analyst_error}")
                analyst_signals.append(
                    AnalystSignal(
                        signal=Signal.NEUTRAL,
                        justification=f"[Error] {analyst_key} failed: {analyst_error}",
                    )
                )

        # Calculate priority score
        priority_score = adapter._calculate_priority_score(analyst_signals)

        return {
            "ticker": ticker,
            "price": price,
            "analyst_signals": analyst_signals,
            "priority_score": priority_score,
            "summary": {
                "bullish_count": sum(1 for s in analyst_signals if adapter._signal_label(s) == "BULLISH"),
                "bearish_count": sum(1 for s in analyst_signals if adapter._signal_label(s) == "BEARISH"),
                "neutral_count": sum(1 for s in analyst_signals if adapter._signal_label(s) == "NEUTRAL"),
                "avg_confidence": sum(getattr(s, 'confidence', 0.5) for s in analyst_signals) / len(analyst_signals) if analyst_signals else 0.0,
                "signal_consistency": adapter._calculate_signal_consistency(analyst_signals)
            }
        }
    except Exception as e:
        import traceback
        logger.error(f"Error collecting signals for {ticker} on {trading_date}: {e}")
        logger.error(traceback.format_exc())
        return {
            "ticker": ticker,
            "price": price,
            "analyst_signals": [],
            "priority_score": 0.0,
            "summary": {
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "avg_confidence": 0.0,
                "signal_consistency": 0.0
            }
        }


def _load_shared_analyst_signals(
    adapter: Any,
    trading_date: str,
    ticker: str,
    analyst_key: str,
    llm_config: Dict[str, Any],
    input_signature: Optional[str] = None,
):
    if adapter.shared_analyst_cache is None:
        return None
    try:
        signals = adapter.shared_analyst_cache.load(
            trading_date=trading_date,
            market=adapter.market,
            ticker=ticker,
            analyst_key=analyst_key,
            llm_provider=str(llm_config.get("provider", "")),
            llm_model=str(llm_config.get("model", "")),
            input_signature=input_signature,
        )
    except Exception as cache_error:
        logger.warning(
            f"Shared analyst cache load failed for {analyst_key} {ticker} {trading_date}: {cache_error}"
        )
        return None
    if signals is not None:
        logger.debug(f"Shared analyst cache hit: {analyst_key} {ticker} {trading_date}")
    return signals


def _save_shared_analyst_signals(
    adapter: Any,
    trading_date: str,
    ticker: str,
    analyst_key: str,
    llm_config: Dict[str, Any],
    analyst_signals: List[Any],
    input_signature: Optional[str] = None,
) -> None:
    if adapter.shared_analyst_cache is None or not analyst_signals:
        return
    if any(adapter._signal_has_error(signal) for signal in analyst_signals):
        return
    try:
        adapter.shared_analyst_cache.save(
            trading_date=trading_date,
            market=adapter.market,
            ticker=ticker,
            analyst_key=analyst_key,
            llm_provider=str(llm_config.get("provider", "")),
            llm_model=str(llm_config.get("model", "")),
            analyst_signals=analyst_signals,
            input_signature=input_signature,
        )
    except Exception as cache_error:
        logger.warning(
            f"Shared analyst cache save failed for {analyst_key} {ticker} {trading_date}: {cache_error}"
        )


def _signal_has_error(signal: Any) -> bool:
    justification = getattr(signal, "justification", "")
    if not isinstance(justification, str):
        return False
    return justification.startswith("[Error]")


def collect_signals_only(
    adapter: Any,
    trading_date: str,
    prices: Dict[str, float]
) -> Dict[str, Any]:
    """
    只收集分析师信号，不做最终交易决策。
    用于 B1 方案：先收集所有股票信号，再统一做组合分配。

    Args:
        trading_date: 交易日期 (YYYY-MM-DD)
        prices: {ticker: price} 当前价格

    Returns:
        {ticker: dict} 每只股票的聚合信号，保留 summary 以兼容 profile-specific logic
    """
    # Use enhanced version with smart priority
    enhanced_signals = adapter.collect_signals_only_parallel_v2(trading_date, prices)

    # Convert to old format for backward compatibility
    signals = {}
    for ticker, data in enhanced_signals.items():
        summary = dict(data.get("summary", {}) or {})
        bullish = int(summary.get("bullish_count", 0) or 0)
        bearish = int(summary.get("bearish_count", 0) or 0)
        neutral = int(summary.get("neutral_count", 0) or 0)
        signals[ticker] = {
            "ticker": ticker,
            "signal": adapter._aggregate_signal_from_summary(summary),
            "justification": (
                "Enhanced signals with priority score "
                f"{data.get('priority_score', 0.0)}; counts "
                f"B={bullish}, N={neutral}, BR={bearish}"
            ),
            "confidence": summary.get("avg_confidence", 0.5),
            "summary": summary,
            "priority_score": data.get("priority_score", 0.0),
            "analyst_signals": list(data.get("analyst_signals", []) or []),
        }

    return signals


def collect_signals_only_parallel_v2(
    adapter: Any,
    trading_date: str,
    prices: Dict[str, float],
    max_workers: int = 5,
    prefetched_analyst_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Enhanced parallel version for smart priority sorting.
    Collects ALL analyst signals with priority scores.

    Args:
        trading_date: 交易日期 (YYYY-MM-DD)
        prices: {ticker: price} 当前价格
        max_workers: 最大并行线程数 (默认 5)

    Returns:
        {ticker: EnhancedSignal} 包含所有分析师信号和优先级评分
    """
    signals = {}
    signals_lock = Lock()

    try:
        from util.db_helper import db_initialize, get_db
        from database.sqlite_helper import SQLiteDB

        db_initialize(use_local_db=True, db_path=adapter.db_path)
        db = get_db()
        if isinstance(db, SQLiteDB):
            db.set_db_path(adapter.db_path)

        trading_date_dt = datetime.strptime(trading_date, "%Y-%m-%d")

        # Build workflow config (shared across all threads)
        config = {
            "llm": {
                "provider": adapter.llm_provider,
                "model": adapter.llm_model
            },
            "tickers": adapter.tickers,
            "exp_name": adapter.exp_name,
            "trading_date": trading_date_dt,
            "cashflow": adapter.current_portfolio["cashflow"],
            "workflow_analysts": adapter.analysts,
            "planner_mode": False,
            "personality": adapter.personality,
            "api_source": adapter.api_source,
            "prefetched_analyst_inputs": prefetched_analyst_inputs or {},
        }

        # Create Portfolio dict for serialization across threads
        portfolio_dict = {
            "id": adapter.current_portfolio["id"],
            "cashflow": adapter.current_portfolio["cashflow"],
            "positions": adapter.current_portfolio["positions"]
        }

        # Filter tickers that have prices
        tickers_to_process = [t for t in adapter.tickers if t in prices]
        if len(tickers_to_process) < len(adapter.tickers):
            missing = set(adapter.tickers) - set(tickers_to_process)
            logger.warning(f"No price for {missing} on {trading_date}, skipping")

        # Process tickers in parallel using ThreadPoolExecutor
        logger.info(f"Processing {len(tickers_to_process)} tickers with {max_workers} workers for smart priority")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_ticker = {
                executor.submit(
                    adapter._process_single_ticker_for_signals_v2,
                    ticker,
                    trading_date,
                    trading_date_dt,
                    prices[ticker],
                    config,
                    portfolio_dict
                ): ticker
                for ticker in tickers_to_process
            }

            # Collect results as they complete
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    result = future.result()
                    if result:
                        with signals_lock:
                            signals[result["ticker"]] = result
                except Exception as e:
                    logger.error(f"Thread error for {ticker}: {e}")
                    with signals_lock:
                        signals[ticker] = {
                            "ticker": ticker,
                            "price": prices.get(ticker, 0.0),
                            "analyst_signals": [],
                            "priority_score": 0.0,
                            "summary": {
                                "bullish_count": 0,
                                "bearish_count": 0,
                                "neutral_count": 0,
                                "avg_confidence": 0.0,
                                "signal_consistency": 0.0
                            }
                        }

    except ImportError as e:
        logger.error(f"Failed to import DeepFund modules: {e}")
        # Return empty signals for all
        for ticker in adapter.tickers:
            if ticker in prices:
                signals[ticker] = {
                    "ticker": ticker,
                    "price": prices[ticker],
                    "analyst_signals": [],
                    "priority_score": 0.0,
                    "summary": {
                        "bullish_count": 0,
                        "bearish_count": 0,
                        "neutral_count": 0,
                        "avg_confidence": 0.0,
                        "signal_consistency": 0.0
                    }
                }

    finally:
        pass

    logger.info(f"Collected enhanced signals for {len(signals)} tickers on {trading_date}")
    return signals
