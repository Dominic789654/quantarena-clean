"""
Multi-Personality Parallel Backtest Engine
==========================================

多人格并行回测引擎，支持多种投资人格同时运行并对比分析。

特性:
- 共享数据层: K线数据只获取一次，复用给所有人格
- 进程级并行: N个人格独立运行，互不干扰
- 详细对比报告: 收益率、风险指标、交易行为等多维度对比
"""

import json
import time
import traceback
from copy import deepcopy
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import multiprocessing as mp
from loguru import logger

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()
from shared.utils.run_id import generate_run_id

from backtest.base_engine import BaseBacktestEngine
from backtest.data_loader import DataPrefetcher
from backtest.portfolio_tracker import PortfolioTracker
from backtest.metrics import PerformanceMetrics
from backtest.engine import BacktestEngine, BacktestResult, create_backtest_engine
from backtest.workflow_adapter import SharedPhase1Artifact, create_workflow_adapter
from backtest.report import ReportGenerator
from backtest.report_metric_fallbacks import enrich_behavior_metrics
from quantarena.news_diagnostics import drain_news_diagnostics
from quantarena.report_artifacts import RunReportArtifacts, load_run_report_artifacts


def _load_run_metrics_from_artifacts(report_dir: Path) -> Dict[str, Any]:
    """Load metrics from a generated report directory without report side effects."""
    artifacts = load_run_report_artifacts(report_dir)
    if not artifacts.metrics:
        return {}
    try:
        return enrich_behavior_metrics(artifacts.metrics, report_dir)
    except Exception as exc:
        logger.warning(f"Failed to enrich report artifact metrics from {report_dir}: {exc}")
        return {}


def _summarize_trade_rows(
    artifacts: RunReportArtifacts,
    trading_days: int,
    default_trade_count: int = 0,
) -> Tuple[int, int, int, float]:
    """Summarize buy/sell counts from loaded trade rows."""
    if not artifacts.trades:
        return default_trade_count, 0, 0, 0.0

    actions = [str(trade.get("action") or "").upper() for trade in artifacts.trades]
    buy_count = len([action for action in actions if action == "BUY"])
    sell_count = len([action for action in actions if action == "SELL"])
    trade_count = len(artifacts.trades)
    trading_freq = trade_count / max(1, trading_days)
    return trade_count, buy_count, sell_count, trading_freq


@dataclass
class PersonalityResult:
    """单个人格的回测结果"""
    personality: str
    result: BacktestResult
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    trade_count: int
    win_rate: float
    avg_position_days: float
    token_usage: Dict[str, Any] = field(default_factory=dict)
    error_count: int = 0
    duration_seconds: float = 0.0


@dataclass
class MultiPersonalityComparison:
    """多人格对比结果"""
    run_id: str
    start_date: str
    end_date: str
    tickers: List[str]
    market: str
    trading_days: int
    personality_results: Dict[str, PersonalityResult] = field(default_factory=dict)
    daily_decisions: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # date -> personality -> decisions
    shared_data_stats: Dict[str, Any] = field(default_factory=dict)
    total_duration: float = 0.0


class SharedDataCache:
    """
    共享数据缓存层

    只获取一次数据，复用给所有人格:
    - K-line 数据
    - 基本面数据
    - 新闻数据

    注意: 使用 DataPrefetcher 与 BaseBacktestEngine 共享数据获取逻辑
    """

    def __init__(self, tickers: List[str], start_date: str, end_date: str,
                 market: str = "cn", db_path: str = "data/signal_flux.db",
                 analysts: Optional[List[str]] = None):
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.market = market
        self.db_path = db_path
        self.analysts = analysts or ["fundamental", "technical", "company_news"]

        # 使用与 BaseBacktestEngine 相同的 DataPrefetcher
        self.prefetcher = DataPrefetcher(db_path=db_path, market=market)
        self._kline_cache: Dict[str, Dict] = {}
        self._trading_days: List[str] = []
        self._stats = {
            "kline_fetch_time": 0.0,
            "cache_hits": 0
        }

    def prefetch_all(self) -> Dict[str, Any]:
        """预取所有共享数据"""
        logger.info("=" * 60)
        logger.info("SHARED DATA CACHE: Prefetching data for all personalities")
        logger.info("=" * 60)

        start_time = time.time()

        # 1. 预取 K-line 数据
        kline_start = time.time()
        self._prefetch_klines()
        self._stats["kline_fetch_time"] = time.time() - kline_start

        # 2. 获取交易日列表
        self._trading_days = self.prefetcher.get_trading_days(
            start_date=self.start_date,
            end_date=self.end_date
        )

        total_time = time.time() - start_time
        self._stats["total_time"] = total_time

        logger.info(f"Shared data cache ready: {len(self._trading_days)} trading days")
        logger.info(f"Cache stats: {self._format_stats()}")

        return self._stats

    def _prefetch_klines(self):
        """预取所有股票的 K-line 数据"""
        logger.info(f"Prefetching K-line data for {len(self.tickers)} tickers...")

        self.prefetcher.prefetch_klines(
            tickers=self.tickers,
            start_date=self.start_date,
            end_date=self.end_date,
            force_sync=False
        )

        # 缓存到内存 - 使用 get_cached_prices 获取数据
        for ticker in self.tickers:
            # 获取该股票的所有日期数据
            trading_days = self.prefetcher.get_trading_days(self.start_date, self.end_date)
            ticker_data = []
            for date in trading_days:
                price_data = self.prefetcher.get_cached_prices(ticker, date)
                if price_data:
                    ticker_data.append({
                        'date': date,
                        'open': price_data.get('open'),
                        'close': price_data.get('close'),
                        'high': price_data.get('high'),
                        'low': price_data.get('low'),
                        'volume': price_data.get('volume')
                    })
            if ticker_data:
                self._kline_cache[ticker] = ticker_data

        logger.info(f"K-line cache: {len(self._kline_cache)} tickers loaded")


    def get_prices_for_date(self, date: str) -> Dict[str, float]:
        """获取某天的所有股票价格"""
        prices = {}
        for ticker in self.tickers:
            price_data = self.prefetcher.get_cached_prices(ticker, date)
            if price_data:
                prices[ticker] = price_data['close']
        return prices

    def get_kline_for_ticker(self, ticker: str) -> Optional[Dict]:
        """获取某只股票的 K-line 数据"""
        return self._kline_cache.get(ticker)

    def get_trading_days(self) -> List[str]:
        """获取交易日列表"""
        return self._trading_days.copy()

    def _format_stats(self) -> str:
        return f"K-line: {self._stats['kline_fetch_time']:.2f}s"

    def close(self):
        """关闭资源"""
        if self.prefetcher:
            self.prefetcher.close()


def run_single_personality(
    personality: str,
    tickers: List[str],
    start_date: str,
    end_date: str,
    initial_cash: float,
    market: str,
    analysts: List[str],
    db_path: str,
    shared_data_stats: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
    shared_analyst_cache_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    运行单个人格的回测（用于进程池并行）

    Args:
        personality: 投资人格
        shared_data_stats: 共享数据的统计信息（用于报告）

    Returns:
        Dict with personality result data (serializable for multiprocessing)
    """
    logger.info(f"[PROCESS START] {personality} agent starting...")
    start_time = time.time()

    # 导入 token tracker
    try:
        from llm.inference import reset_token_tracker, get_token_stats
        reset_token_tracker()
    except Exception:
        pass

    error_count = 0
    result = None
    run_id = generate_run_id(f"mp_{personality}")

    try:
        # 创建独立的回测引擎
        engine = create_backtest_engine(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            market=market,
            config=deepcopy(config) if config else None,
            use_llm=use_llm,
            analysts=analysts,
            personality=personality,
            portfolio_mode=True,
            db_path=db_path,
            shared_analyst_cache_dir=shared_analyst_cache_dir,
        )

        # 运行回测
        result = engine.run(prefetch=False, generate_report=True, run_id=run_id)

        engine.close()

    except Exception as e:
        logger.error(f"[{personality}] Error during backtest: {e}")
        logger.error(traceback.format_exc())
        error_count += 1

    duration = time.time() - start_time

    # Read metrics from the generated report artifacts (more reliable than pickle)
    report_dir = Path("reports/backtest") / run_id
    metrics_from_artifacts = _load_run_metrics_from_artifacts(report_dir)
    if metrics_from_artifacts:
        logger.info(f"[{personality}] Loaded metrics from {report_dir / 'metrics.json'}")

    # Extract metrics from file or result
    if metrics_from_artifacts:
        m = metrics_from_artifacts
        total_return = m.get("total_return", 0)
        max_drawdown = m.get("max_drawdown", 0)
        sharpe_ratio = m.get("sharpe_ratio", 0)
        trade_count = m.get("total_trades", 0)
        win_rate = m.get("win_rate", 0)
        avg_position_days = m.get("avg_position_days", 0)
    elif result:
        metrics = dict(result.metrics or {})
        if not metrics:
            metrics = PerformanceMetrics.calculate_all(
                result.tracker,
                result.tracker.trades[-1].price if result.tracker.trades else 0
            )
        m = metrics
        total_return = metrics.get('total_return', 0)
        max_drawdown = metrics.get('max_drawdown', 0)
        sharpe_ratio = metrics.get('sharpe_ratio', 0)
        trade_count = metrics.get('total_trades', len(result.tracker.trades))
        avg_position_days = metrics.get('avg_position_days', 0)

        if "win_rate" in metrics:
            win_rate = metrics.get("win_rate", 0)
        else:
            # Calculate win rate
            trades = result.tracker.trades
            buy_trades = [t for t in trades if t.action == "BUY"]
            sell_trades = [t for t in trades if t.action == "SELL"]
            win_count = 0
            for sell in sell_trades:
                avg_buy_price = sum(t.price * t.shares for t in buy_trades) / sum(t.shares for t in buy_trades) if buy_trades else 0
                if sell.price > avg_buy_price:
                    win_count += 1
            win_rate = (win_count / len(sell_trades) * 100) if sell_trades else 0
    else:
        m = {}
        total_return = 0
        max_drawdown = 0
        sharpe_ratio = 0
        trade_count = 0
        win_rate = 0
        avg_position_days = 0

    # 获取 token 使用情况
    token_usage = {}
    try:
        from llm.inference import get_token_stats
        token_usage = get_token_stats()
    except Exception:
        pass

    # Return a plain dictionary (serializable for multiprocessing)
    return {
        "personality": personality,
        "run_id": run_id,
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "trade_count": trade_count,
        "win_rate": win_rate / 100 if win_rate > 1 else win_rate,  # Normalize to 0-1
        "avg_position_days": avg_position_days,
        "metrics": m,
        "token_usage": token_usage,
        "error_count": error_count,
        "duration_seconds": duration
    }


class MultiPersonalityBacktest(BaseBacktestEngine):
    """
    多人格并行回测主类 - 继承 BaseBacktestEngine

    使用示例:
    ```python
    mp_backtest = MultiPersonalityBacktest(
        tickers=["600519", "000858"],
        start_date="2025-10-01",
        end_date="2025-10-31",
        personalities=["conservative", "balanced", "aggressive", "passive"]
    )

    comparison = mp_backtest.run()
    ```
    """

    def __init__(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        personalities: List[str] = None,
        initial_cash: float = 100000.0,
        market: str = "cn",
        config: Optional[Dict[str, Any]] = None,
        db_path: str = "data/signal_flux.db",
        use_llm: bool = True,
        analysts: Optional[List[str]] = None,
        max_workers: Optional[int] = None
    ):
        # 调用基类初始化
        super().__init__(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            market=market,
            config=config,
            db_path=db_path,
            use_llm=use_llm,
            analysts=analysts,
            personality="balanced"  # 基类需要，但多人格不使用单一人格
        )

        # 多人格特有的初始化
        self.personalities = personalities or ["conservative", "balanced", "aggressive", "passive"]
        self.max_workers = max_workers or min(len(self.personalities), mp.cpu_count())

        self.run_id = generate_run_id()
        self.shared_cache: Optional[SharedDataCache] = None
        self.comparison: Optional[MultiPersonalityComparison] = None
        self.shared_analyst_cache_dir = str(Path("data/backtest/shared_analyst_cache") / self.run_id)
        self.shared_phase1_cache_dir = str(Path("data/backtest/shared_phase1_artifacts"))

        logger.info("=" * 60)
        logger.info("MULTI-PERSONALITY BACKTEST INITIALIZED")
        logger.info("=" * 60)
        logger.info(f"Tickers: {', '.join(tickers)}")
        logger.info(f"Period: {start_date} to {end_date}")
        logger.info(f"Personalities: {', '.join(self.personalities)}")
        logger.info(f"Analysts: {', '.join(self.analysts)}")
        logger.info(f"Max parallel workers: {self.max_workers}")

    def run(self, prefetch: bool = True, generate_report: bool = True, run_id: Optional[str] = None) -> MultiPersonalityComparison:
        """
        运行多人格并行回测

        Args:
            prefetch: 是否预取共享数据
            generate_report: 是否生成对比报告
            run_id: 可选的运行ID（未使用，保持接口一致）

        Returns:
            MultiPersonalityComparison: 详细的对比结果
        """
        start_time = time.time()

        if prefetch or not self.shared_cache:
            self._prefetch_shared_data()

        if self.use_llm:
            self._ensure_shared_stats_defaults()
            personality_results, daily_decisions = self._run_day_shared_phase1(generate_report=generate_report)
        else:
            results = self._run_parallel()
            personality_results = self._build_personality_results_from_parallel(results)
            daily_decisions = {}

        self.comparison = MultiPersonalityComparison(
            run_id=self.run_id,
            start_date=self.start_date,
            end_date=self.end_date,
            tickers=self.tickers,
            market=self.market,
            trading_days=len(self.shared_cache.get_trading_days()) if self.shared_cache else 0,
            personality_results=personality_results,
            daily_decisions=daily_decisions,
            shared_data_stats=self.shared_cache._stats if self.shared_cache else {},
            total_duration=time.time() - start_time,
        )

        if generate_report:
            self._generate_comparison_report()

        self.close()
        logger.info(f"Multi-personality backtest completed in {self.comparison.total_duration:.2f}s")
        return self.comparison

    def close(self):
        """清理资源 - 重写基类方法"""
        if self.shared_cache:
            self.shared_cache.close()
        super().close()

    def _ensure_shared_stats_defaults(self) -> None:
        """Ensure shared cache stats expose all phase1/phase2 orchestration fields."""
        if not self.shared_cache:
            return
        self.shared_cache._stats.setdefault("shared_analyst_cache_dir", self.shared_analyst_cache_dir)
        self.shared_cache._stats.setdefault("shared_phase1_cache_dir", self.shared_phase1_cache_dir)
        self.shared_cache._stats.setdefault("execution_mode", "day_shared_phase1")
        self.shared_cache._stats.setdefault("shared_phase1_days", 0)
        self.shared_cache._stats.setdefault("shared_phase1_errors", 0)
        self.shared_cache._stats.setdefault("shared_phase1_token_usage", self._empty_token_stats())
        self.shared_cache._stats.setdefault("shared_phase1_artifact_cache_hits", 0)
        self.shared_cache._stats.setdefault("shared_phase1_artifact_cache_misses", 0)
        self.shared_cache._stats.setdefault("shared_phase1_prefetch_submitted", 0)
        self.shared_cache._stats.setdefault("shared_phase1_prefetch_hits", 0)
        self.shared_cache._stats.setdefault("shared_phase1_prefetch_failures", 0)
        self.shared_cache._stats.setdefault("shared_phase1_sync_load_seconds", 0.0)
        self.shared_cache._stats.setdefault("shared_phase1_prefetch_compute_seconds", 0.0)
        self.shared_cache._stats.setdefault("shared_phase1_prefetch_wait_seconds", 0.0)
        self.shared_cache._stats.setdefault("shared_phase1_prefetch_fallback_sync_seconds", 0.0)
        self.shared_cache._stats.setdefault("shared_phase1_prefetch_hit_rate", 0.0)
        self.shared_cache._stats.setdefault("shared_phase1_pipeline_hidden_seconds", 0.0)
        self.shared_cache._stats.setdefault("shared_phase1_pipeline_utilization", 0.0)
        self.shared_cache._stats.setdefault("phase2_execution_mode", "parallel_threads")

    def _prefetch_shared_data(self):
        """预取共享数据"""
        self.shared_cache = SharedDataCache(
            tickers=self.tickers,
            start_date=self.start_date,
            end_date=self.end_date,
            market=self.market,
            db_path=self.db_path,
            analysts=self.analysts,
        )
        self.shared_cache.prefetch_all()
        Path(self.shared_analyst_cache_dir).mkdir(parents=True, exist_ok=True)
        Path(self.shared_phase1_cache_dir).mkdir(parents=True, exist_ok=True)
        self._ensure_shared_stats_defaults()

    @staticmethod
    def _empty_token_stats() -> Dict[str, Any]:
        return {
            "total_input": 0,
            "total_output": 0,
            "calls": 0,
            "by_agent": {},
        }

    @classmethod
    def _merge_token_stats(cls, current: Optional[Dict[str, Any]], delta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        merged = deepcopy(current or cls._empty_token_stats())
        delta = delta or cls._empty_token_stats()
        merged["total_input"] += delta.get("total_input", 0)
        merged["total_output"] += delta.get("total_output", 0)
        merged["calls"] += delta.get("calls", 0)
        by_agent = merged.setdefault("by_agent", {})
        for agent, stats in (delta.get("by_agent") or {}).items():
            agent_stats = by_agent.setdefault(agent, {"input": 0, "output": 0, "calls": 0})
            agent_stats["input"] += stats.get("input", 0)
            agent_stats["output"] += stats.get("output", 0)
            agent_stats["calls"] += stats.get("calls", 0)
        return merged

    @staticmethod
    def _is_shared_phase1_engine(engine: BacktestEngine) -> bool:
        return bool(
            engine.use_llm
            and engine.workflow_adapter
            and engine.smart_priority_mode
            and not engine._is_equal_weight_personality()
        )

    def _create_personality_engines(self) -> Dict[str, BacktestEngine]:
        engines: Dict[str, BacktestEngine] = {}
        for personality in self.personalities:
            # Use factory function for all personas that need special engine classes
            if personality in {"fof", "macro_tactical", "tactical_allocation", "fundamental_value", "value", 
                              "behavioral_momentum", "momentum", "smart_beta_passive", "smart_beta"}:
                engine = create_backtest_engine(
                    tickers=self.tickers,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    initial_cash=self.initial_cash,
                    market=self.market,
                    config=deepcopy(self.config) if self.config else None,
                    use_llm=self.use_llm,
                    analysts=self.analysts,
                    personality=personality,
                    portfolio_mode=True,
                    db_path=self.db_path,
                    shared_analyst_cache_dir=self.shared_analyst_cache_dir,
                    shared_phase1_cache_dir=self.shared_phase1_cache_dir,
                )
            else:
                # Default for generic personas
                engine = BacktestEngine(
                    tickers=self.tickers,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    initial_cash=self.initial_cash,
                    market=self.market,
                    config=deepcopy(self.config) if self.config else None,
                    use_llm=self.use_llm,
                    analysts=self.analysts,
                    personality=personality,
                    portfolio_mode=True,
                    db_path=self.db_path,
                    shared_analyst_cache_dir=self.shared_analyst_cache_dir,
                    shared_phase1_cache_dir=self.shared_phase1_cache_dir,
                )
            engines[personality] = engine
        return engines

    def _record_shared_phase1_artifact_stats(self, artifact: Optional[SharedPhase1Artifact], *, prefetched: bool = False) -> None:
        if not self.shared_cache:
            return
        self.shared_cache._stats["shared_phase1_days"] = self.shared_cache._stats.get("shared_phase1_days", 0) + 1
        if artifact is not None and artifact.metadata.get("cache_hit"):
            self.shared_cache._stats["shared_phase1_artifact_cache_hits"] = (
                self.shared_cache._stats.get("shared_phase1_artifact_cache_hits", 0) + 1
            )
        else:
            self.shared_cache._stats["shared_phase1_artifact_cache_misses"] = (
                self.shared_cache._stats.get("shared_phase1_artifact_cache_misses", 0) + 1
            )
        if prefetched:
            self.shared_cache._stats["shared_phase1_prefetch_hits"] = (
                self.shared_cache._stats.get("shared_phase1_prefetch_hits", 0) + 1
            )

    def _load_shared_phase1_artifact(
        self,
        shared_signal_adapter,
        date: str,
        prices: Dict[str, float],
        phase1_workers: int,
    ) -> Tuple[SharedPhase1Artifact, float]:
        try:
            from llm.inference import set_token_scope
        except Exception:
            def set_token_scope(scope_name):
                return None

        started_at = time.time()
        set_token_scope("shared_phase1")
        try:
            artifact = shared_signal_adapter.load_or_compute_shared_phase1(
                trading_date=date,
                prices=prices,
                max_workers=phase1_workers,
            )
            return artifact, time.time() - started_at
        finally:
            set_token_scope(None)

    def _finalize_shared_phase1_stats(self) -> None:
        if not self.shared_cache:
            return
        stats = self.shared_cache._stats
        prefetch_submitted = stats.get("shared_phase1_prefetch_submitted", 0)
        prefetch_hits = stats.get("shared_phase1_prefetch_hits", 0)
        prefetch_compute_seconds = stats.get("shared_phase1_prefetch_compute_seconds", 0.0)
        prefetch_wait_seconds = stats.get("shared_phase1_prefetch_wait_seconds", 0.0)
        hidden_seconds = max(0.0, prefetch_compute_seconds - prefetch_wait_seconds)
        stats["shared_phase1_prefetch_hit_rate"] = (
            prefetch_hits / prefetch_submitted if prefetch_submitted else 0.0
        )
        stats["shared_phase1_pipeline_hidden_seconds"] = hidden_seconds
        stats["shared_phase1_pipeline_utilization"] = (
            hidden_seconds / prefetch_compute_seconds if prefetch_compute_seconds else 0.0
        )

    def _run_personality_phase2_day(
        self,
        personality: str,
        engine: BacktestEngine,
        date: str,
        prices: Dict[str, float],
        enhanced_signals: Optional[Dict[str, Any]],
        priority_order: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Execute one personality's day-level phase2 in its own thread."""
        try:
            from llm.inference import set_token_scope
        except Exception:
            def set_token_scope(scope_name):
                return None

        decisions: Dict[str, Dict[str, Any]] = {}
        error_message: Optional[str] = None
        started_at = time.time()
        set_token_scope(f"personality:{personality}")
        try:
            if engine._is_equal_weight_personality():
                decisions = engine._generate_equal_weight_index_decisions(date, prices)
            elif enhanced_signals is not None and self._is_shared_phase1_engine(engine):
                decisions = engine._generate_llm_decisions_with_precollected_signals(
                    date,
                    prices,
                    deepcopy(enhanced_signals),
                    priority_order=list(priority_order or []),
                )
            else:
                decisions = engine._generate_decisions(date, prices)

            engine._execute_day_with_decisions(date, prices, decisions)
        except Exception as e:
            logger.error(f"[{personality}] Error during shared-day execution on {date}: {e}")
            logger.error(traceback.format_exc())
            error_message = f"{date}: {str(e)}"
            decisions = {
                ticker: {
                    "action": "HOLD",
                    "shares": 0,
                    "justification": f"Shared day error: {str(e)}",
                    "_applied": False,
                }
                for ticker in prices
            }
            engine._execute_day_with_decisions(date, prices, decisions)
        finally:
            set_token_scope(None)

        return {
            "personality": personality,
            "decisions": decisions,
            "error": error_message,
            "duration_seconds": time.time() - started_at,
        }

    def _build_personality_results_from_parallel(self, results: List[Dict[str, Any]]) -> Dict[str, PersonalityResult]:
        personality_results: Dict[str, PersonalityResult] = {}
        for r in results:
            metrics = dict(r.get("metrics") or {})
            if not metrics:
                metrics = {
                    "total_return": r.get("total_return", 0),
                    "max_drawdown": r.get("max_drawdown", 0),
                    "sharpe_ratio": r.get("sharpe_ratio", 0),
                    "total_trades": r.get("trade_count", 0),
                    "win_rate": r.get("win_rate", 0),
                    "avg_position_days": r.get("avg_position_days", 0),
                }
            personality_results[r["personality"]] = PersonalityResult(
                personality=r["personality"],
                result=BacktestResult(
                    run_id=r.get("run_id", ""),
                    start_date=self.start_date,
                    end_date=self.end_date,
                    tickers=self.tickers,
                    market=self.market,
                    initial_cash=self.initial_cash,
                    tracker=PortfolioTracker(initial_cash=self.initial_cash, tickers=self.tickers),
                    metrics=metrics,
                    errors=[],
                ),
                total_return=r.get("total_return", 0),
                max_drawdown=r.get("max_drawdown", 0),
                sharpe_ratio=r.get("sharpe_ratio", 0),
                trade_count=r.get("trade_count", 0),
                win_rate=r.get("win_rate", 0),
                avg_position_days=metrics.get("avg_position_days", r.get("avg_position_days", 0)),
                token_usage=r.get("token_usage", {}),
                error_count=r.get("error_count", 0),
                duration_seconds=r.get("duration_seconds", 0.0),
            )
        return personality_results

    @staticmethod
    def _resolve_behavior_metrics(result: PersonalityResult) -> Dict[str, Any]:
        metrics = dict(getattr(result.result, "metrics", {}) or {}) if result.result else {}
        run_id = getattr(result.result, "run_id", "") if result.result else ""
        report_dir = Path("reports/backtest") / run_id if run_id else None
        return enrich_behavior_metrics(metrics, report_dir)

    def _run_day_shared_phase1(self, generate_report: bool) -> tuple[Dict[str, PersonalityResult], Dict[str, Dict[str, Any]]]:
        logger.info("=" * 60)
        logger.info(f"STARTING DAY-ORCHESTRATED BACKTEST: {len(self.personalities)} personalities")
        logger.info("=" * 60)

        try:
            from llm.inference import get_token_stats, reset_token_tracker, set_token_scope
            token_scope_available = True
        except Exception:
            token_scope_available = False

            def reset_token_tracker(scope_name=None):
                return None

            def get_token_stats(scope_name=None):
                return self._empty_token_stats()

            def set_token_scope(scope_name):
                return None

        reset_token_tracker()
        reset_token_tracker("shared_phase1")

        engines = self._create_personality_engines()
        for personality in self.personalities:
            reset_token_tracker(f"personality:{personality}")

        shared_signal_adapter = None
        if any(self._is_shared_phase1_engine(engine) for engine in engines.values()):
            shared_signal_adapter = create_workflow_adapter(
                tickers=self.tickers,
                initial_cash=self.initial_cash,
                market=self.market,
                use_llm=True,
                analysts=self.analysts,
                personality="balanced",
                db_path=self.db_path,
                shared_analyst_cache_dir=self.shared_analyst_cache_dir,
                shared_phase1_cache_dir=self.shared_phase1_cache_dir,
            )

        trading_days = self.shared_cache.get_trading_days() if self.shared_cache else []
        runtime: Dict[str, Dict[str, Any]] = {
            personality: {
                "run_id": generate_run_id(f"mp_{personality}"),
                "duration_seconds": 0.0,
                "error_count": 0,
                "errors": [],
                "token_usage": self._empty_token_stats(),
            }
            for personality in self.personalities
        }
        daily_decisions: Dict[str, Dict[str, Any]] = {}

        prefetch_executor = None
        next_artifact_future = None
        next_prefetch_date = None

        try:
            for day_num, date in enumerate(trading_days, 1):
                logger.info(f"[{day_num}/{len(trading_days)}] Processing shared day {date}...")
                prices = self.shared_cache.get_prices_for_date(date) if self.shared_cache else {}
                if not prices:
                    logger.warning(f"No prices available for {date}, skipping")
                    continue

                artifact: Optional[SharedPhase1Artifact] = None
                enhanced_signals: Optional[Dict[str, Any]] = None
                priority_order: Optional[List[str]] = None
                if shared_signal_adapter is not None:
                    phase1_workers = min(5, max(1, len(prices)))
                    prefetched = False
                    try:
                        if next_prefetch_date == date and next_artifact_future is not None:
                            wait_started_at = time.time()
                            try:
                                artifact, prefetch_compute_seconds = next_artifact_future.result()
                                prefetched = True
                                if self.shared_cache:
                                    self.shared_cache._stats["shared_phase1_prefetch_compute_seconds"] = (
                                        self.shared_cache._stats.get("shared_phase1_prefetch_compute_seconds", 0.0)
                                        + prefetch_compute_seconds
                                    )
                            except Exception as prefetch_error:
                                logger.warning(f"Shared phase1 prefetch failed for {date}, falling back to sync compute: {prefetch_error}")
                                if self.shared_cache:
                                    self.shared_cache._stats["shared_phase1_prefetch_failures"] = (
                                        self.shared_cache._stats.get("shared_phase1_prefetch_failures", 0) + 1
                                    )
                                artifact, sync_load_seconds = self._load_shared_phase1_artifact(
                                    shared_signal_adapter,
                                    date,
                                    prices,
                                    phase1_workers,
                                )
                                if self.shared_cache:
                                    self.shared_cache._stats["shared_phase1_sync_load_seconds"] = (
                                        self.shared_cache._stats.get("shared_phase1_sync_load_seconds", 0.0)
                                        + sync_load_seconds
                                    )
                                    self.shared_cache._stats["shared_phase1_prefetch_fallback_sync_seconds"] = (
                                        self.shared_cache._stats.get("shared_phase1_prefetch_fallback_sync_seconds", 0.0)
                                        + sync_load_seconds
                                    )
                            finally:
                                if self.shared_cache:
                                    self.shared_cache._stats["shared_phase1_prefetch_wait_seconds"] = (
                                        self.shared_cache._stats.get("shared_phase1_prefetch_wait_seconds", 0.0)
                                        + (time.time() - wait_started_at)
                                    )
                                next_artifact_future = None
                                next_prefetch_date = None
                        else:
                            artifact, sync_load_seconds = self._load_shared_phase1_artifact(
                                shared_signal_adapter,
                                date,
                                prices,
                                phase1_workers,
                            )
                            if self.shared_cache:
                                self.shared_cache._stats["shared_phase1_sync_load_seconds"] = (
                                    self.shared_cache._stats.get("shared_phase1_sync_load_seconds", 0.0)
                                    + sync_load_seconds
                                )
                        enhanced_signals = artifact.enhanced_signals
                        priority_order = artifact.priority_order
                    except Exception as e:
                        logger.error(f"Shared phase1 failed on {date}: {e}")
                        logger.error(traceback.format_exc())
                        artifact = None
                        enhanced_signals = None
                        priority_order = None
                        if self.shared_cache:
                            self.shared_cache._stats["shared_phase1_errors"] = self.shared_cache._stats.get("shared_phase1_errors", 0) + 1
                    self._record_shared_phase1_artifact_stats(artifact, prefetched=prefetched)

                    next_index = day_num
                    if next_index < len(trading_days):
                        next_date = trading_days[next_index]
                        next_prices = self.shared_cache.get_prices_for_date(next_date) if self.shared_cache else {}
                        if next_prices:
                            if prefetch_executor is None:
                                prefetch_executor = ThreadPoolExecutor(max_workers=1)
                            next_prefetch_date = next_date
                            next_artifact_future = prefetch_executor.submit(
                                self._load_shared_phase1_artifact,
                                shared_signal_adapter,
                                next_date,
                                next_prices,
                                min(5, max(1, len(next_prices))),
                            )
                            if self.shared_cache:
                                self.shared_cache._stats["shared_phase1_prefetch_submitted"] = (
                                    self.shared_cache._stats.get("shared_phase1_prefetch_submitted", 0) + 1
                                )

                daily_decisions[date] = {}
                max_workers = max(1, min(self.max_workers, len(engines)))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(
                            self._run_personality_phase2_day,
                            personality,
                            engine,
                            date,
                            prices,
                            enhanced_signals,
                            priority_order,
                        ): personality
                        for personality, engine in engines.items()
                    }
                    for future in as_completed(futures):
                        payload = future.result()
                        personality = payload["personality"]
                        runtime[personality]["duration_seconds"] += payload["duration_seconds"]
                        if payload["error"]:
                            runtime[personality]["error_count"] += 1
                            runtime[personality]["errors"].append(payload["error"])
                        daily_decisions[date][personality] = payload["decisions"]
        finally:
            if prefetch_executor:
                prefetch_executor.shutdown(wait=True, cancel_futures=True)
            if shared_signal_adapter:
                shared_signal_adapter.close()

        if self.shared_cache and token_scope_available:
            self.shared_cache._stats["shared_phase1_token_usage"] = get_token_stats("shared_phase1")
        self._finalize_shared_phase1_stats()

        personality_results: Dict[str, PersonalityResult] = {}
        for personality, engine in engines.items():
            if token_scope_available:
                runtime[personality]["token_usage"] = get_token_stats(f"personality:{personality}")
            try:
                result = engine.finalize_run(
                    trading_days=trading_days,
                    run_id=runtime[personality]["run_id"],
                    generate_report=generate_report,
                    errors=runtime[personality]["errors"],
                    token_stats_override=runtime[personality]["token_usage"],
                )
                metrics = result.metrics or {}
                personality_results[personality] = PersonalityResult(
                    personality=personality,
                    result=result,
                    total_return=metrics.get("total_return", 0),
                    max_drawdown=metrics.get("max_drawdown", 0),
                    sharpe_ratio=metrics.get("sharpe_ratio", 0),
                    trade_count=metrics.get("total_trades", 0),
                    win_rate=metrics.get("win_rate", 0),
                    avg_position_days=metrics.get("avg_position_days", 0),
                    token_usage=runtime[personality]["token_usage"],
                    error_count=runtime[personality]["error_count"],
                    duration_seconds=runtime[personality]["duration_seconds"],
                )
            except Exception as e:
                logger.error(f"[{personality}] Failed to finalize day-orchestrated backtest: {e}")
                logger.error(traceback.format_exc())
                personality_results[personality] = PersonalityResult(
                    personality=personality,
                    result=BacktestResult(
                        run_id=runtime[personality]["run_id"],
                        start_date=self.start_date,
                        end_date=self.end_date,
                        tickers=self.tickers,
                        market=self.market,
                        initial_cash=self.initial_cash,
                        tracker=PortfolioTracker(initial_cash=self.initial_cash, tickers=self.tickers),
                        metrics={},
                        errors=[str(e)],
                    ),
                    total_return=0,
                    max_drawdown=0,
                    sharpe_ratio=0,
                    trade_count=0,
                    win_rate=0,
                    avg_position_days=0,
                    token_usage=runtime[personality]["token_usage"],
                    error_count=runtime[personality]["error_count"] + 1,
                    duration_seconds=runtime[personality]["duration_seconds"],
                )
            finally:
                engine.close()

        return personality_results, daily_decisions

    def _run_parallel(self) -> List[Dict[str, Any]]:
        """并行运行各人格回测"""
        logger.info("=" * 60)
        logger.info(f"STARTING PARALLEL BACKTEST: {len(self.personalities)} personalities")
        logger.info("=" * 60)

        results = []

        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    run_single_personality,
                    personality,
                    self.tickers,
                    self.start_date,
                    self.end_date,
                    self.initial_cash,
                    self.market,
                    self.analysts,
                    self.db_path,
                    self.shared_cache._stats if self.shared_cache else {},
                    self.config,
                    self.use_llm,
                    self.shared_analyst_cache_dir,
                ): personality
                for personality in self.personalities
            }

            for future in as_completed(futures):
                personality = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    logger.info(f"[COMPLETED] {personality}: Return={result['total_return']:+.2f}%, Duration={result['duration_seconds']:.2f}s")
                except Exception as e:
                    logger.error(f"[FAILED] {personality}: {e}")
                    results.append({
                        "personality": personality,
                        "run_id": None,
                        "total_return": 0,
                        "max_drawdown": 0,
                        "sharpe_ratio": 0,
                        "trade_count": 0,
                        "win_rate": 0,
                        "avg_position_days": 0,
                        "error_count": 1,
                        "duration_seconds": 0,
                        "token_usage": {},
                    })

        return results

    def _generate_comparison_report(self):
        """生成详细对比报告"""
        if not self.comparison:
            return

        report_dir = Path("reports/multi_personality") / self.run_id
        report_dir.mkdir(parents=True, exist_ok=True)

        # 1. Markdown 报告
        self._generate_markdown_report(report_dir)

        # 2. JSON 数据
        self._generate_json_report(report_dir)

        # 3. CSV 汇总
        self._generate_csv_summary(report_dir)

        # 4. Machine-readable diagnostics
        self._generate_daily_decisions_jsonl(report_dir)
        self._generate_news_diagnostics_jsonl(report_dir)

        logger.info(f"Comparison reports saved to: {report_dir}")

    def _generate_markdown_report(self, report_dir: Path):
        """生成 Markdown 对比报告"""
        c = self.comparison

        shared_stats = c.shared_data_stats or {}
        prefetch_submitted = shared_stats.get("shared_phase1_prefetch_submitted", 0)
        prefetch_hits = shared_stats.get("shared_phase1_prefetch_hits", 0)
        prefetch_hit_rate = shared_stats.get("shared_phase1_prefetch_hit_rate", 0.0) * 100
        prefetch_compute_seconds = shared_stats.get("shared_phase1_prefetch_compute_seconds", 0.0)
        prefetch_wait_seconds = shared_stats.get("shared_phase1_prefetch_wait_seconds", 0.0)
        prefetch_overlap_seconds = shared_stats.get("shared_phase1_pipeline_hidden_seconds", 0.0)
        pipeline_utilization = shared_stats.get("shared_phase1_pipeline_utilization", 0.0) * 100

        lines = [
            "# 多人格投资风格对比回测报告\n",
            f"**运行ID**: `{c.run_id}`\n",
            f"**回测周期**: {c.start_date} ~ {c.end_date} ({c.trading_days} 个交易日)\n",
            f"**股票池**: {', '.join(c.tickers)}\n",
            f"**市场**: {c.market.upper()}\n",
            f"**初始资金**: ¥{self.initial_cash:,.0f}\n",
            f"**总耗时**: {c.total_duration:.2f} 秒\n",
            "\n---\n\n",
            "## 共享数据缓存统计\n",
            f"- K-line 数据获取时间: {shared_stats.get('kline_fetch_time', 0):.2f}s\n",
            f"- 数据缓存总时间: {shared_stats.get('total_time', 0):.2f}s\n",
            f"- shared phase1 artifact cache 命中: {shared_stats.get('shared_phase1_artifact_cache_hits', 0)}\n",
            f"- shared phase1 artifact cache 未命中: {shared_stats.get('shared_phase1_artifact_cache_misses', 0)}\n",
            f"- shared phase1 同步装载耗时: {shared_stats.get('shared_phase1_sync_load_seconds', 0.0):.2f}s\n",
            f"- shared phase1 预取提交次数: {prefetch_submitted}\n",
            f"- shared phase1 预取命中次数: {prefetch_hits} ({prefetch_hit_rate:.1f}%)\n",
            f"- shared phase1 预取失败次数: {shared_stats.get('shared_phase1_prefetch_failures', 0)}\n",
            f"- shared phase1 预取后台耗时: {prefetch_compute_seconds:.2f}s\n",
            f"- shared phase1 进入新交易日等待耗时: {prefetch_wait_seconds:.2f}s\n",
            f"- shared phase1 pipeline 隐藏耗时: {prefetch_overlap_seconds:.2f}s\n",
            f"- shared phase1 pipeline 利用率: {pipeline_utilization:.1f}%\n",
            f"- shared phase1 预取失败后同步回退耗时: {shared_stats.get('shared_phase1_prefetch_fallback_sync_seconds', 0.0):.2f}s\n",
            "\n---\n\n",
            "## 各人格表现对比\n",
            self._generate_performance_table(),
            "\n---\n\n",
            "## 详细指标分析\n",
            self._generate_detailed_analysis(),
            "\n---\n\n",
            "## Token 使用统计\n",
            self._generate_token_table(),
            "\n---\n\n",
            "## 交易行为对比\n",
            self._generate_trading_behavior_table(),
            "\n---\n\n",
            "## Behavior Metrics\n",
            self._generate_behavior_metrics_table(),
            "\n---\n\n",
            "## 结论与建议\n",
            self._generate_conclusions(),
        ]

        report_path = report_dir / "comparison_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def _generate_performance_table(self) -> str:
        """生成表现对比表格"""
        lines = ["### 收益与风险指标\n\n"]
        lines.append("| 人格 | 总收益率 | 最大回撤 | 夏普比率 | 最终资产 | 排名 |\n")
        lines.append("|------|----------|----------|----------|----------|------|\n")

        # 按收益率排序
        sorted_results = sorted(
            self.comparison.personality_results.values(),
            key=lambda x: x.total_return,
            reverse=True
        )

        for i, r in enumerate(sorted_results, 1):
            final_value = self.initial_cash * (1 + r.total_return / 100)
            lines.append(
                f"| **{r.personality}** | "
                f"{r.total_return:+.2f}% | "
                f"{r.max_drawdown:.2f}% | "
                f"{r.sharpe_ratio:.2f} | "
                f"¥{final_value:,.0f} | "
                f"{i} |\n"
            )

        return "".join(lines)

    def _generate_detailed_analysis(self) -> str:
        """生成详细分析"""
        lines = []

        for personality, result in self.comparison.personality_results.items():
            lines.append(f"\n### {personality.upper()} 详细分析\n\n")

            if result.error_count > 0:
                lines.append(f"⚠️ **警告**: 运行中出现 {result.error_count} 个错误\n\n")

            lines.append(f"- **运行耗时**: {result.duration_seconds:.2f} 秒\n")
            lines.append(f"- **交易次数**: {result.trade_count} 次\n")
            win_rate = result.win_rate
            win_rate_pct = win_rate * 100 if win_rate <= 1 else win_rate
            lines.append(f"- **胜率**: {win_rate_pct:.1f}%\n")
            lines.append(f"- **平均持仓天数**: {result.avg_position_days:.1f} 天\n")

            # Token 使用
            token_usage = result.token_usage
            if token_usage:
                calls = token_usage.get('calls', 0)
                input_tokens = token_usage.get('total_input', 0)
                output_tokens = token_usage.get('total_output', 0)
                total_tokens = input_tokens + output_tokens
                cost = (input_tokens / 1_000_000 * 1) + (output_tokens / 1_000_000 * 2)

                lines.append("\n**LLM 调用统计**:\n")
                lines.append(f"- 调用次数: {calls}\n")
                lines.append(f"- 输入 Token: {input_tokens:,}\n")
                lines.append(f"- 输出 Token: {output_tokens:,}\n")
                lines.append(f"- 总 Token: {total_tokens:,}\n")
                lines.append(f"- 预估成本: ¥{cost:.4f}\n")

        return "".join(lines)

    def _generate_token_table(self) -> str:
        """生成 Token 使用表格"""
        lines = ["### 各人格 LLM Token 消耗\n\n"]
        lines.append("| 人格 | 调用次数 | 输入 Token | 输出 Token | 预估成本 |\n")
        lines.append("|------|----------|------------|------------|----------|\n")

        total_cost = 0
        shared_token_usage = (self.comparison.shared_data_stats or {}).get("shared_phase1_token_usage", {})
        if shared_token_usage and shared_token_usage.get("calls", 0) > 0:
            shared_input = shared_token_usage.get("total_input", 0)
            shared_output = shared_token_usage.get("total_output", 0)
            shared_cost = (shared_input / 1_000_000 * 1) + (shared_output / 1_000_000 * 2)
            total_cost += shared_cost
            lines.append(
                f"| shared_phase1 | "
                f"{shared_token_usage.get('calls', 0)} | "
                f"{shared_input:,} | "
                f"{shared_output:,} | "
                f"¥{shared_cost:.4f} |\n"
            )

        for personality, result in self.comparison.personality_results.items():
            token_usage = result.token_usage
            if token_usage:
                calls = token_usage.get('calls', 0)
                input_tokens = token_usage.get('total_input', 0)
                output_tokens = token_usage.get('total_output', 0)
                cost = (input_tokens / 1_000_000 * 1) + (output_tokens / 1_000_000 * 2)
                total_cost += cost

                lines.append(
                    f"| {personality} | "
                    f"{calls} | "
                    f"{input_tokens:,} | "
                    f"{output_tokens:,} | "
                    f"¥{cost:.4f} |\n"
                )
            else:
                lines.append(f"| {personality} | - | - | - | - |\n")

        lines.append(f"| **总计** | - | - | - | **¥{total_cost:.4f}** |\n")

        return "".join(lines)

    def _generate_trading_behavior_table(self) -> str:
        """生成交易行为对比"""
        lines = ["### 交易频率与风格\n\n"]
        lines.append("| 人格 | 交易次数 | 买入次数 | 卖出次数 | 交易频率 | 平均持仓 |\n")
        lines.append("|------|----------|----------|----------|----------|----------|\n")

        for personality, result in self.comparison.personality_results.items():
            # Try to load trades from the individual report if available
            trade_count = result.trade_count
            buy_count = 0
            sell_count = 0
            trading_freq = 0
            avg_position = result.avg_position_days

            run_id = result.result.run_id if result.result else ""
            if run_id:
                report_dir = Path("reports/backtest") / run_id
                artifacts = load_run_report_artifacts(report_dir)
                trade_count, buy_count, sell_count, trading_freq = _summarize_trade_rows(
                    artifacts,
                    self.comparison.trading_days,
                    default_trade_count=trade_count,
                )

            lines.append(
                f"| {personality} | "
                f"{trade_count} | "
                f"{buy_count} | "
                f"{sell_count} | "
                f"{trading_freq:.2f} | "
                f"{avg_position:.1f} 天 |\n"
            )

        return "".join(lines)

    def _generate_behavior_metrics_table(self) -> str:
        """Generate unified behavior diagnostics table."""
        lines = ["### 行为诊断指标\n\n"]
        lines.append("| 人格 | 平均换手 | 平均现金占比 | 平均总暴露 | 价值一致性 | 动量缩放激活率 | 熔断触发次数 |\n")
        lines.append("|------|----------|--------------|------------|------------|------------------|--------------|\n")

        for personality, result in self.comparison.personality_results.items():
            metrics = self._resolve_behavior_metrics(result)
            avg_turnover = float(metrics.get("avg_turnover_ratio", 0.0) or 0.0)
            avg_cash = float(metrics.get("avg_cash_ratio", 0.0) or 0.0)
            avg_exposure = float(metrics.get("avg_gross_exposure", 0.0) or 0.0)
            value_score = metrics.get("value_consistency_score")
            vol_activation = metrics.get("vol_scaling_activation_rate")
            crash_count = metrics.get("crash_breaker_trigger_count")

            value_text = f"{float(value_score):.4f}" if value_score is not None else "-"
            vol_text = f"{float(vol_activation):.4f}" if vol_activation is not None else "-"
            crash_text = f"{float(crash_count):.0f}" if crash_count is not None else "-"

            lines.append(
                f"| {personality} | "
                f"{avg_turnover:.2%} | "
                f"{avg_cash:.2%} | "
                f"{avg_exposure:.2%} | "
                f"{value_text} | "
                f"{vol_text} | "
                f"{crash_text} |\n"
            )

        return "".join(lines)

    def _generate_conclusions(self) -> str:
        """生成结论"""
        lines = []

        # 找出最佳和最差
        sorted_results = sorted(
            self.comparison.personality_results.values(),
            key=lambda x: x.total_return,
            reverse=True
        )

        if sorted_results:
            best = sorted_results[0]
            worst = sorted_results[-1]

            lines.append("\n### 关键发现\n\n")
            lines.append(f"1. **最佳表现**: **{best.personality}** 人格，收益率 {best.total_return:+.2f}%\n")
            lines.append(f"2. **最差表现**: **{worst.personality}** 人格，收益率 {worst.total_return:+.2f}%\n")

            diff = best.total_return - worst.total_return
            lines.append(f"3. **收益差距**: 最佳与最差之间相差 {diff:.2f} 个百分点\n")

            # 风险调整后收益
            lines.append("\n### 风险调整后表现\n\n")
            sharpe_sorted = sorted(
                sorted_results,
                key=lambda x: x.sharpe_ratio,
                reverse=True
            )
            if sharpe_sorted:
                best_sharpe = sharpe_sorted[0]
                lines.append(f"- **最高夏普比率**: {best_sharpe.personality} ({best_sharpe.sharpe_ratio:.2f})\n")

            lines.append("\n### 人格特征验证\n\n")
            for r in sorted_results:
                if r.personality == "conservative":
                    lines.append(f"- **保守型**: 回撤 {r.max_drawdown:.2f}%，交易 {r.trade_count} 次 - "
                               f"{'符合' if r.max_drawdown > -10 else '偏激进'}预期\n")
                elif r.personality == "aggressive":
                    lines.append(f"- **激进型**: 收益率 {r.total_return:+.2f}%，交易 {r.trade_count} 次 - "
                               f"{'符合' if r.trade_count > 5 else '偏保守'}预期\n")

        return "".join(lines)

    def _generate_json_report(self, report_dir: Path):
        """生成 JSON 格式报告"""
        # Convert dataclasses to dictionaries for JSON serialization
        personality_results_dict = {}
        for personality, result in self.comparison.personality_results.items():
            personality_results_dict[personality] = {
                "personality": result.personality,
                "total_return": result.total_return,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
                "trade_count": result.trade_count,
                "win_rate": result.win_rate,
                "avg_position_days": result.avg_position_days,
                "metrics": self._resolve_behavior_metrics(result),
                "token_usage": result.token_usage,
                "error_count": result.error_count,
                "duration_seconds": result.duration_seconds,
                "run_id": result.result.run_id if result.result else ""
            }

        data = {
            "run_id": self.comparison.run_id,
            "artifact_schema_version": 2,
            "config": {
                "tickers": self.comparison.tickers,
                "start_date": self.comparison.start_date,
                "end_date": self.comparison.end_date,
                "market": self.comparison.market,
                "trading_days": self.comparison.trading_days,
                "initial_cash": self.initial_cash,
                "analysts": self.analysts
            },
            "shared_data_stats": self.comparison.shared_data_stats,
            "total_duration": self.comparison.total_duration,
            "personality_results": personality_results_dict
        }

        json_path = report_dir / "comparison_data.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _normalize_decision_record(
        *,
        date: str,
        personality: str,
        ticker: str,
        decision: Any,
    ) -> Dict[str, Any]:
        """Return a JSON-safe, stable decision record for report artifacts."""
        if hasattr(decision, "__dict__") and not isinstance(decision, dict):
            raw_decision = dict(decision.__dict__)
        elif isinstance(decision, dict):
            raw_decision = dict(decision)
        else:
            raw_decision = {"value": decision}

        metadata = {
            key: value
            for key, value in raw_decision.items()
            if isinstance(key, str) and key.startswith("_")
        }
        record = {
            "date": date,
            "personality": personality,
            "ticker": ticker,
            "action": raw_decision.get("action"),
            "shares": raw_decision.get("shares"),
            "price": raw_decision.get("price"),
            "justification": raw_decision.get("justification"),
            "applied": raw_decision.get("_applied"),
            "risk_reasons": raw_decision.get("_risk_reasons", []),
            "metadata": metadata,
        }
        extra = {
            key: value
            for key, value in raw_decision.items()
            if key not in {"action", "shares", "price", "justification", "_applied", "_risk_reasons"}
            and not (isinstance(key, str) and key.startswith("_"))
        }
        if extra:
            record["extra"] = extra
        return ReportGenerator._json_safe(record)

    def _iter_daily_decision_records(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for date in sorted(self.comparison.daily_decisions):
            by_personality = self.comparison.daily_decisions.get(date) or {}
            for personality in sorted(by_personality):
                decisions = by_personality.get(personality) or {}
                if not isinstance(decisions, dict):
                    records.append(
                        ReportGenerator._json_safe(
                            {
                                "date": date,
                                "personality": personality,
                                "ticker": None,
                                "action": None,
                                "shares": None,
                                "price": None,
                                "justification": None,
                                "applied": None,
                                "risk_reasons": [],
                                "metadata": {},
                                "extra": {"value": decisions},
                            }
                        )
                    )
                    continue
                for ticker in sorted(decisions):
                    records.append(
                        self._normalize_decision_record(
                            date=date,
                            personality=personality,
                            ticker=ticker,
                            decision=decisions[ticker],
                        )
                    )
        return records

    def _generate_daily_decisions_jsonl(self, report_dir: Path) -> None:
        """Export per-date/personality/ticker decisions as JSONL."""
        path = report_dir / "daily_decisions.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for record in self._iter_daily_decision_records():
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _generate_news_diagnostics_jsonl(self, report_dir: Path) -> None:
        """Export count-only company-news provider diagnostics as JSONL."""
        path = report_dir / "news_diagnostics.jsonl"
        records = [ReportGenerator._json_safe(record) for record in drain_news_diagnostics()]
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _generate_csv_summary(self, report_dir: Path):
        """生成 CSV 汇总"""
        import csv

        csv_path = report_dir / "personality_summary.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Personality", "Total Return %", "Max Drawdown %", "Sharpe Ratio",
                "Trade Count", "Win Rate %", "Avg Position Days", "Avg Turnover Ratio",
                "Avg Cash Ratio", "Avg Gross Exposure", "Duration Sec", "Error Count"
            ])

            for personality, result in self.comparison.personality_results.items():
                win_rate = result.win_rate
                win_rate_pct = win_rate * 100 if win_rate <= 1 else win_rate
                metrics = self._resolve_behavior_metrics(result)
                writer.writerow([
                    personality,
                    f"{result.total_return:.2f}",
                    f"{result.max_drawdown:.2f}",
                    f"{result.sharpe_ratio:.2f}",
                    result.trade_count,
                    f"{win_rate_pct:.1f}",
                    f"{result.avg_position_days:.1f}",
                    f"{float(metrics.get('avg_turnover_ratio', 0.0) or 0.0):.4f}",
                    f"{float(metrics.get('avg_cash_ratio', 0.0) or 0.0):.4f}",
                    f"{float(metrics.get('avg_gross_exposure', 0.0) or 0.0):.4f}",
                    f"{result.duration_seconds:.2f}",
                    result.error_count
                ])


# 便捷函数
def run_multi_personality_backtest(
    tickers: List[str],
    start_date: str,
    end_date: str,
    personalities: List[str] = None,
    initial_cash: float = 100000.0,
    market: str = "cn",
    analysts: Optional[List[str]] = None,
    db_path: str = "data/signal_flux.db",
    config: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
    max_workers: Optional[int] = None,
) -> MultiPersonalityComparison:
    """
    便捷函数：运行多人格并行回测

    Returns:
        MultiPersonalityComparison: 详细的对比结果
    """
    mp = MultiPersonalityBacktest(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        personalities=personalities,
        initial_cash=initial_cash,
        market=market,
        config=config,
        analysts=analysts,
        db_path=db_path,
        use_llm=use_llm,
        max_workers=max_workers,
    )

    return mp.run()
