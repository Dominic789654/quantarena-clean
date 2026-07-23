"""
FOF Backtest Engine
===================

Backtest engine for a fund-of-funds style meta personality that combines
multiple underlying personality sleeves into one portfolio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from loguru import logger

from backtest.engine import BacktestEngine
from backtest.fof_allocator import FOFAllocator, FOFAllocationResult, SleeveSnapshot
from backtest.mandate_interface import allocate_with_mandate

if TYPE_CHECKING:
    from backtest.portfolio_allocator import PortfolioAllocator


class FOFBacktestEngine(BacktestEngine):
    """Meta-allocation engine that combines sleeve-level personality outputs."""

    DEFAULT_SLEEVES = ["conservative", "balanced", "aggressive", "passive"]
    DEFAULT_SLEEVE_ALIASES = {
        "conservative": "conservative",
        "balanced": "balanced",
        "aggressive": "aggressive",
        "passive": "passive",
        "equal_weight_index": "equal_weight_index",
        "equal_weight": "equal_weight_index",
        "ewi": "equal_weight_index",
        "fof": "fof",
    }

    def __init__(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        initial_cash: float = 100000.0,
        market: str = "cn",
        config: Optional[Dict[str, Any]] = None,
        db_path: str = "data/signal_flux.db",
        use_llm: bool = False,
        analysts: Optional[List[str]] = None,
        personality: str = "fof",
        portfolio_mode: bool = True,
        smart_priority_mode: bool = True,
        shared_analyst_cache_dir: Optional[str] = None,
        shared_phase1_cache_dir: Optional[str] = None,
    ):
        from backtest.portfolio_allocator import PortfolioAllocator

        fof_config = dict((config or {}).get("fof", {}))
        normalized_fof_config = self._normalize_fof_config(
            fof_config,
            allocator_cls=PortfolioAllocator,
        )
        fof_config = normalized_fof_config
        normalized_sleeves = list(fof_config.get("sleeves", self.DEFAULT_SLEEVES))
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
            personality=personality,
            portfolio_mode=False,
            smart_priority_mode=False,
            shared_analyst_cache_dir=shared_analyst_cache_dir,
            shared_phase1_cache_dir=shared_phase1_cache_dir,
        )
        self.personality = "fof"
        self.fof_config = fof_config
        self.fof_sleeves = list(normalized_sleeves)
        self.fof_allocator = FOFAllocator(fof_config)
        self.sleeve_allocators: Dict[str, PortfolioAllocator] = {
            sleeve: self._init_portfolio_allocator(sleeve) for sleeve in self.fof_sleeves
        }
        self.last_fof_allocation: Optional[FOFAllocationResult] = None
        self.fof_daily_allocations: List[Dict[str, Any]] = []
        self._prev_prices_for_attribution: Dict[str, float] = {}
        self._pending_rebalance_stats: Dict[str, Any] = {}
        self.config = {
            **(self.config or {}),
            "personality": "fof",
            "fof": {
                "sleeves": list(self.fof_sleeves),
                **fof_config,
            },
        }
        logger.info(f"FOFBacktestEngine initialized with sleeves={self.fof_sleeves}")

    @classmethod
    def _normalize_fof_config(
        cls,
        fof_config: Optional[Dict[str, Any]],
        *,
        allocator_cls,
    ) -> Dict[str, Any]:
        config = dict(fof_config or {})
        aliases = dict(getattr(allocator_cls, "PERSONALITY_ALIASES", {}) or cls.DEFAULT_SLEEVE_ALIASES)
        raw_sleeves = list(config.get("sleeves", cls.DEFAULT_SLEEVES) or cls.DEFAULT_SLEEVES)
        base_weights = dict(config.get("base_weights", {}) or {})
        normalized_sleeves: List[str] = []
        sleeve_configs: List[Dict[str, Any]] = []
        seen = set()

        for raw_sleeve in raw_sleeves:
            item = cls._normalize_fof_sleeve_item(raw_sleeve, aliases=aliases)
            if item is None:
                continue
            personality = item["personality"]
            if personality in seen:
                if item.get("base_weight") is not None:
                    base_weights[personality] = item["base_weight"]
                continue
            seen.add(personality)
            normalized_sleeves.append(personality)
            sleeve_configs.append(item)
            if item.get("base_weight") is not None:
                base_weights[personality] = item["base_weight"]

        if not normalized_sleeves:
            raise ValueError("FOF requires at least one valid non-meta sleeve personality")

        config["sleeves"] = normalized_sleeves
        config["sleeve_configs"] = sleeve_configs
        if base_weights:
            config["base_weights"] = base_weights
        return config

    @classmethod
    def _normalize_fof_sleeve_item(
        cls,
        raw_sleeve: Any,
        *,
        aliases: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        if isinstance(raw_sleeve, dict):
            if raw_sleeve.get("enabled", True) is False:
                return None
            name = raw_sleeve.get("personality", raw_sleeve.get("name", ""))
            base_weight = raw_sleeve.get("base_weight", raw_sleeve.get("weight"))
        else:
            name = raw_sleeve
            base_weight = None

        name = str(name).strip().lower()
        if not name:
            return None
        if name not in aliases:
            raise ValueError(f"Unknown FOF sleeve personality: {raw_sleeve}")
        canonical = aliases[name]
        if canonical == "fof":
            raise ValueError("FOF sleeves cannot include the 'fof' meta personality")

        normalized = {"personality": canonical}
        if base_weight is not None:
            weight_value = float(base_weight)
            if weight_value <= 0:
                raise ValueError(f"FOF sleeve base_weight must be positive: {raw_sleeve}")
            normalized["base_weight"] = weight_value
        return normalized

    def _generate_decisions(self, date: str, prices: Dict[str, float]) -> Dict[str, Dict]:
        if self.use_llm and self.workflow_adapter:
            return self._generate_fof_decisions(date, prices)
        return self._generate_simple_decisions(prices)

    def _generate_fof_decisions(self, date: str, prices: Dict[str, float]) -> Dict[str, Dict]:
        from backtest.portfolio_allocator import Portfolio as AllocatorPortfolio

        enhanced_signals = self.workflow_adapter.collect_signals_only_parallel_v2(trading_date=date, prices=prices)
        simplified_signals = self._build_allocatable_signals(enhanced_signals)
        alloc_portfolio = AllocatorPortfolio(
            cashflow=self.current_portfolio["cashflow"],
            positions={
                ticker: int(pos.get("shares", 0)) for ticker, pos in self.current_portfolio["positions"].items()
            },
        )

        sleeves: Dict[str, SleeveSnapshot] = {}
        for sleeve_name, allocator in self.sleeve_allocators.items():
            target_positions = allocate_with_mandate(
                allocator,
                signals=simplified_signals,
                current_portfolio=alloc_portfolio,
                prices=prices,
                trading_date=date,
                decision_memory=self.decision_memory[-5:] if self.decision_memory else None,
            )
            sleeves[sleeve_name] = SleeveSnapshot(
                personality=sleeve_name,
                target_weights=target_positions,
                metrics={
                    "gross_exposure": sum(max(float(v), 0.0) for v in target_positions.values()),
                    "ticker_count": float(sum(1 for v in target_positions.values() if v > 0)),
                },
                metadata={
                    "date": date,
                },
            )

        market_context = self._build_market_context(enhanced_signals)
        allocation = self.fof_allocator.allocate(sleeves=sleeves, market_context=market_context)
        self.last_fof_allocation = allocation
        self._record_fof_allocation(date, allocation, sleeves=sleeves, prices=prices)
        sleeve_consensus = self._build_sleeve_consensus(
            {sleeve_name: dict(snapshot.target_weights or {}) for sleeve_name, snapshot in sleeves.items()}
        )
        decisions = self._rebalance_to_target_positions(
            target_positions=allocation.final_stock_weights,
            prices=prices,
            date=date,
            sleeve_weights=allocation.sleeve_weights,
            rationale=allocation.rationale,
            regime=allocation.diagnostics.get("regime"),
            sleeve_consensus=sleeve_consensus,
        )
        if self.fof_daily_allocations:
            self.fof_daily_allocations[-1]["rebalance_stats"] = dict(self._pending_rebalance_stats or {})
            self.config.setdefault("fof", {})["daily_allocations"] = list(self.fof_daily_allocations)

        for ticker, decision in decisions.items():
            self.decision_memory.append(
                {
                    "trading_date": date,
                    "ticker": ticker,
                    "action": decision.get("action", "HOLD"),
                    "shares": decision.get("shares", 0),
                    "price": prices.get(ticker, 0.0),
                    "strategy": "fof",
                }
            )
        logger.info(
            "FOF decisions for {}: {}".format(
                date,
                [(ticker, item["action"], item["shares"]) for ticker, item in decisions.items()],
            )
        )
        return decisions

    def _record_fof_allocation(
        self,
        date: str,
        allocation: FOFAllocationResult,
        *,
        sleeves: Dict[str, SleeveSnapshot],
        prices: Dict[str, float],
    ) -> None:
        self._finalize_previous_fof_attribution(prices)

        sleeve_target_weights = {
            sleeve_name: dict(snapshot.target_weights or {})
            for sleeve_name, snapshot in sleeves.items()
        }
        snapshot = {
            "date": date,
            "regime": allocation.diagnostics.get("regime", "unknown"),
            "sleeve_weights": dict(allocation.sleeve_weights),
            "sleeve_target_weights": sleeve_target_weights,
            "sleeve_consensus": self._build_sleeve_consensus(sleeve_target_weights),
            "rebalance_stats": dict(self._pending_rebalance_stats or {}),
            "final_stock_weights": dict(allocation.final_stock_weights),
            "sleeve_returns": {
                sleeve: 0.0
                for sleeve in allocation.sleeve_weights
            },
            "sleeve_contributions": {
                sleeve: 0.0
                for sleeve in allocation.sleeve_weights
            },
            "estimated_total_contribution": 0.0,
            "attribution_complete": False,
            "rationale": allocation.rationale,
        }
        self.fof_daily_allocations.append(snapshot)
        self.config.setdefault("fof", {})["daily_allocations"] = list(self.fof_daily_allocations)
        self._prev_prices_for_attribution = {
            ticker: float(price)
            for ticker, price in (prices or {}).items()
            if price is not None and float(price) > 0
        }

    def _finalize_previous_fof_attribution(self, prices: Dict[str, float]) -> None:
        if not self.fof_daily_allocations or not self._prev_prices_for_attribution:
            return

        previous_snapshot = self.fof_daily_allocations[-1]
        sleeve_target_weights = previous_snapshot.get("sleeve_target_weights") or {}
        sleeve_returns = self._estimate_sleeve_returns(sleeve_target_weights, prices)
        sleeve_weights = previous_snapshot.get("sleeve_weights") or {}
        sleeve_contributions = {
            sleeve: float(sleeve_weights.get(sleeve, 0.0) or 0.0) * float(sleeve_returns.get(sleeve, 0.0) or 0.0)
            for sleeve in sleeve_weights
        }
        previous_snapshot["sleeve_returns"] = sleeve_returns
        previous_snapshot["sleeve_contributions"] = sleeve_contributions
        previous_snapshot["estimated_total_contribution"] = sum(sleeve_contributions.values())
        previous_snapshot["attribution_complete"] = True

    def _estimate_sleeve_returns(
        self,
        sleeve_target_weights: Dict[str, Dict[str, float]],
        prices: Dict[str, float],
    ) -> Dict[str, float]:
        if not self._prev_prices_for_attribution:
            return {sleeve: 0.0 for sleeve in sleeve_target_weights}

        sleeve_returns: Dict[str, float] = {}
        for sleeve_name, target_weights in (sleeve_target_weights or {}).items():
            weighted_return = 0.0
            total_weight = 0.0
            for ticker, weight in (target_weights or {}).items():
                prev_price = float(self._prev_prices_for_attribution.get(ticker, 0.0) or 0.0)
                current_price = float((prices or {}).get(ticker, 0.0) or 0.0)
                if prev_price <= 0 or current_price <= 0:
                    continue
                ticker_return = current_price / prev_price - 1.0
                positive_weight = max(float(weight), 0.0)
                weighted_return += positive_weight * ticker_return
                total_weight += positive_weight
            sleeve_returns[sleeve_name] = weighted_return / total_weight if total_weight > 0 else 0.0
        return sleeve_returns

    def _build_sleeve_consensus(
        self,
        sleeve_target_weights: Dict[str, Dict[str, float]],
    ) -> Dict[str, Any]:
        normalized_targets: Dict[str, Dict[str, float]] = {}
        for sleeve_name, targets in (sleeve_target_weights or {}).items():
            normalized_targets[sleeve_name] = {
                ticker: max(float(weight), 0.0)
                for ticker, weight in (targets or {}).items()
                if max(float(weight), 0.0) > 0
            }

        sleeve_names = list(normalized_targets.keys())
        support_counts: Dict[str, int] = {}
        aggregate_weights: Dict[str, float] = {}
        pairwise_overlaps: List[float] = []

        for sleeve_name, targets in normalized_targets.items():
            for ticker, weight in targets.items():
                support_counts[ticker] = support_counts.get(ticker, 0) + 1
                aggregate_weights[ticker] = aggregate_weights.get(ticker, 0.0) + weight

        for idx, left_name in enumerate(sleeve_names):
            left_targets = normalized_targets[left_name]
            left_total = sum(left_targets.values())
            for right_name in sleeve_names[idx + 1:]:
                right_targets = normalized_targets[right_name]
                right_total = sum(right_targets.values())
                denom = max(left_total, right_total, 1e-12)
                overlap = sum(
                    min(left_targets.get(ticker, 0.0), right_targets.get(ticker, 0.0))
                    for ticker in set(left_targets) | set(right_targets)
                )
                pairwise_overlaps.append(overlap / denom if denom > 0 else 0.0)

        top_tickers = []
        sleeve_count = len(sleeve_names)
        for ticker, support_count in sorted(
            support_counts.items(),
            key=lambda item: (
                -item[1],
                -(aggregate_weights.get(item[0], 0.0) / item[1] if item[1] else 0.0),
                -aggregate_weights.get(item[0], 0.0),
                item[0],
            ),
        )[:5]:
            aggregate_weight = aggregate_weights.get(ticker, 0.0)
            top_tickers.append(
                {
                    "ticker": ticker,
                    "support_count": support_count,
                    "support_ratio": support_count / sleeve_count if sleeve_count else 0.0,
                    "average_weight": aggregate_weight / support_count if support_count else 0.0,
                    "aggregate_weight": aggregate_weight,
                }
            )

        average_pairwise_overlap = 1.0 if len(sleeve_names) <= 1 else (
            sum(pairwise_overlaps) / len(pairwise_overlaps) if pairwise_overlaps else 0.0
        )
        return {
            "average_pairwise_overlap": average_pairwise_overlap,
            "distinct_ticker_count": len(support_counts),
            "top_tickers": top_tickers,
        }

    def _build_allocatable_signals(self, enhanced_signals: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        signals: Dict[str, Dict[str, Any]] = {}
        for ticker, payload in (enhanced_signals or {}).items():
            summary = dict(payload.get("summary", {}))
            bullish = int(summary.get("bullish_count", 0))
            bearish = int(summary.get("bearish_count", 0))
            neutral = int(summary.get("neutral_count", 0))
            if bullish > bearish and bullish >= neutral:
                signal = "BULLISH"
            elif bearish > bullish and bearish >= neutral:
                signal = "BEARISH"
            else:
                signal = "NEUTRAL"
            consistency = float(summary.get("signal_consistency", 0.0))
            confidence = float(summary.get("avg_confidence", 0.5))
            signals[ticker] = {
                "ticker": ticker,
                "signal": signal,
                "confidence": max(min(confidence, 1.0), 0.0),
                "justification": (
                    f"Analyst summary: bull={bullish}, bear={bearish}, neutral={neutral}, "
                    f"consistency={consistency:.2f}"
                ),
            }
        return signals

    def _build_market_context(self, enhanced_signals: Dict[str, Any]) -> Dict[str, Any]:
        total_bullish = 0
        total_bearish = 0
        consistencies: List[float] = []
        for payload in (enhanced_signals or {}).values():
            summary = payload.get("summary", {})
            total_bullish += int(summary.get("bullish_count", 0))
            total_bearish += int(summary.get("bearish_count", 0))
            consistencies.append(float(summary.get("signal_consistency", 0.5)))
        total_signals = total_bullish + total_bearish
        signal_bias = 0.0 if total_signals <= 0 else (total_bullish - total_bearish) / total_signals
        avg_consistency = sum(consistencies) / len(consistencies) if consistencies else 0.5
        return {
            "signal_bias": signal_bias,
            "avg_signal_consistency": avg_consistency,
            "bullish_signals": total_bullish,
            "bearish_signals": total_bearish,
        }

    def _resolve_rebalance_threshold_multiplier(
        self,
        *,
        regime: Optional[str] = None,
        sleeve_consensus: Optional[Dict[str, Any]] = None,
    ) -> float:
        multiplier = 1.0
        regime_key = str(regime or "").strip().lower()
        if regime_key == "bear":
            multiplier = max(multiplier, float(self.fof_config.get("bear_rebalance_threshold_multiplier", 1.0) or 1.0))
        elif regime_key == "volatile":
            multiplier = max(multiplier, float(self.fof_config.get("volatile_rebalance_threshold_multiplier", 1.0) or 1.0))

        consensus = sleeve_consensus or {}
        overlap = float(consensus.get("average_pairwise_overlap", 1.0) or 0.0)
        low_overlap_threshold = float(self.fof_config.get("low_consensus_overlap_threshold", 0.0) or 0.0)
        if low_overlap_threshold > 0 and overlap < low_overlap_threshold:
            multiplier = max(multiplier, float(self.fof_config.get("low_consensus_threshold_multiplier", 1.0) or 1.0))
        return max(multiplier, 1.0)

    def _get_rebalance_skip_reason(
        self,
        *,
        current_weight: float,
        target_weight: float,
        trade_value: float,
        total_value: float,
        trade_shares: int,
        regime: Optional[str] = None,
        sleeve_consensus: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        threshold_multiplier = self._resolve_rebalance_threshold_multiplier(
            regime=regime,
            sleeve_consensus=sleeve_consensus,
        )
        min_weight_delta = float(self.fof_config.get("min_rebalance_weight_delta", 0.0) or 0.0) * threshold_multiplier
        min_trade_value_ratio = float(self.fof_config.get("min_rebalance_trade_value_ratio", 0.0) or 0.0) * threshold_multiplier
        min_rebalance_shares = int(self.fof_config.get("min_rebalance_shares", 0) or 0)

        if min_rebalance_shares > 0 and trade_shares < min_rebalance_shares:
            return "min_shares"
        if abs(float(target_weight) - float(current_weight)) < min_weight_delta:
            return "weight_delta"
        if total_value > 0 and min_trade_value_ratio > 0 and (trade_value / total_value) < min_trade_value_ratio:
            return "trade_value_ratio"
        return None

    def _should_skip_rebalance_trade(
        self,
        *,
        current_weight: float,
        target_weight: float,
        trade_value: float,
        total_value: float,
        trade_shares: int,
        regime: Optional[str] = None,
        sleeve_consensus: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if trade_shares <= 0:
            return True
        return self._get_rebalance_skip_reason(
            current_weight=current_weight,
            target_weight=target_weight,
            trade_value=trade_value,
            total_value=total_value,
            trade_shares=trade_shares,
            regime=regime,
            sleeve_consensus=sleeve_consensus,
        ) is not None

    def _rebalance_to_target_positions(
        self,
        target_positions: Dict[str, float],
        prices: Dict[str, float],
        date: str,
        sleeve_weights: Dict[str, float],
        rationale: str,
        *,
        regime: Optional[str] = None,
        sleeve_consensus: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict]:
        decisions: Dict[str, Dict] = {}
        tradable_tickers = [ticker for ticker in self.tickers if ticker in prices and prices[ticker] > 0]
        total_value = self.current_portfolio["cashflow"]
        stats = {
            "executed_buys": 0,
            "executed_sells": 0,
            "skipped_buys": 0,
            "skipped_sells": 0,
            "executed_trade_value": 0.0,
            "skipped_trade_value": 0.0,
            "skip_reason_counts": {
                "weight_delta": 0,
                "trade_value_ratio": 0,
                "min_shares": 0,
            },
        }
        for ticker in tradable_tickers:
            total_value += self.current_portfolio["positions"].get(ticker, {}).get("shares", 0) * prices[ticker]

        target_shares = {
            ticker: int((total_value * max(float(target_positions.get(ticker, 0.0)), 0.0)) / prices[ticker])
            for ticker in tradable_tickers
        }
        current_shares_map = {
            ticker: int(self.current_portfolio["positions"].get(ticker, {}).get("shares", 0))
            for ticker in tradable_tickers
        }
        current_weights = {
            ticker: ((current_shares_map[ticker] * prices[ticker]) / total_value) if total_value > 0 else 0.0
            for ticker in tradable_tickers
        }

        for ticker in tradable_tickers:
            current_shares = current_shares_map[ticker]
            shares_to_sell = max(current_shares - target_shares[ticker], 0)
            trade_value = shares_to_sell * prices[ticker]
            skip_sell_reason = self._get_rebalance_skip_reason(
                current_weight=current_weights[ticker],
                target_weight=float(target_positions.get(ticker, 0.0) or 0.0),
                trade_value=trade_value,
                total_value=total_value,
                trade_shares=shares_to_sell,
                regime=regime,
                sleeve_consensus=sleeve_consensus,
            ) if shares_to_sell > 0 else None
            if shares_to_sell > 0 and not skip_sell_reason:
                self._execute_sell(date, ticker, shares_to_sell, prices[ticker])
                stats["executed_sells"] += 1
                stats["executed_trade_value"] += trade_value
                decisions[ticker] = {
                    "action": "SELL",
                    "shares": shares_to_sell,
                    "justification": self._build_trade_justification(
                        ticker,
                        target_positions.get(ticker, 0.0),
                        sleeve_weights,
                        rationale,
                    ),
                    "_applied": True,
                }
            elif shares_to_sell > 0:
                stats["skipped_sells"] += 1
                stats["skipped_trade_value"] += trade_value
                if skip_sell_reason:
                    stats["skip_reason_counts"][skip_sell_reason] += 1

        for ticker in tradable_tickers:
            current_shares = self.current_portfolio["positions"].get(ticker, {}).get("shares", 0)
            shares_to_buy = max(target_shares[ticker] - current_shares, 0)
            if shares_to_buy > 0:
                affordable = int(self.current_portfolio["cashflow"] / prices[ticker]) if prices[ticker] > 0 else 0
                actual_buy = min(shares_to_buy, affordable)
                trade_value = actual_buy * prices[ticker]
                skip_buy_reason = self._get_rebalance_skip_reason(
                    current_weight=current_weights[ticker],
                    target_weight=float(target_positions.get(ticker, 0.0) or 0.0),
                    trade_value=trade_value,
                    total_value=total_value,
                    trade_shares=actual_buy,
                    regime=regime,
                    sleeve_consensus=sleeve_consensus,
                ) if actual_buy > 0 else None
                if actual_buy > 0 and not skip_buy_reason:
                    self._execute_buy(date, ticker, actual_buy, prices[ticker])
                    stats["executed_buys"] += 1
                    stats["executed_trade_value"] += trade_value
                    decisions[ticker] = {
                        "action": "BUY",
                        "shares": actual_buy,
                        "justification": self._build_trade_justification(
                            ticker,
                            target_positions.get(ticker, 0.0),
                            sleeve_weights,
                            rationale,
                        ),
                        "_applied": True,
                    }
                elif actual_buy > 0:
                    stats["skipped_buys"] += 1
                    stats["skipped_trade_value"] += trade_value
                    if skip_buy_reason:
                        stats["skip_reason_counts"][skip_buy_reason] += 1
            if ticker not in decisions:
                decisions[ticker] = {
                    "action": "HOLD",
                    "shares": 0,
                    "justification": self._build_trade_justification(
                        ticker,
                        target_positions.get(ticker, 0.0),
                        sleeve_weights,
                        rationale,
                    ),
                    "_applied": True,
                }
        stats["executed_trades"] = stats["executed_buys"] + stats["executed_sells"]
        stats["skipped_trades"] = stats["skipped_buys"] + stats["skipped_sells"]
        stats["executed_turnover_ratio"] = (
            stats["executed_trade_value"] / total_value if total_value > 0 else 0.0
        )
        stats["skipped_turnover_ratio"] = (
            stats["skipped_trade_value"] / total_value if total_value > 0 else 0.0
        )
        stats["total_turnover_ratio"] = stats["executed_turnover_ratio"]
        self._pending_rebalance_stats = stats
        return decisions

    @staticmethod
    def _build_trade_justification(
        ticker: str,
        target_weight: float,
        sleeve_weights: Dict[str, float],
        rationale: str,
    ) -> str:
        sleeve_summary = ", ".join(
            f"{name}={weight:.0%}" for name, weight in sorted(sleeve_weights.items()) if weight > 0
        )
        return (
            f"FOF target for {ticker}: {target_weight:.1%}. "
            f"Sleeve mix: {sleeve_summary}. {rationale}"
        )
