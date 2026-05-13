"""
Behavioral Momentum Backtest Engine
===================================

Momentum-oriented backtest engine with:
- 21-day realized volatility scaling
- 5-day market-implied crash breaker
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from backtest.engine import BacktestEngine, BacktestResult
from backtest.mandate_interface import allocate_with_mandate


class BehavioralMomentumBacktestEngine(BacktestEngine):
    """Backtest engine for the scaffolded Behavioral Momentum paradigm."""

    DEFAULT_MOMENTUM_CONFIG: Dict[str, Any] = {
        "target_vol": 0.15,
        "vol_window": 21,
        "market_ma_window": 60,
        "crash_lookback_days": 5,
        "crash_return_threshold": 0.04,
        "crash_exposure_multiplier": 0.2,
        "max_scaling": 1.5,
        "min_scaling": 0.2,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = dict(self.DEFAULT_MOMENTUM_CONFIG)
        cfg.update(dict((self.config or {}).get("momentum", {}) or {}))
        self.momentum_config = cfg
        self._vol_scaling_events = 0
        self._crash_breaker_trigger_count = 0
        self._exposure_multipliers: List[float] = []
        self._momentum_days = 0
        logger.info(f"BehavioralMomentumBacktestEngine initialized with config={self.momentum_config}")

    def _load_price_series(self, ticker: str, date: str, lookback_days: int) -> pd.Series:
        trading_days = self.get_trading_days()
        try:
            idx = trading_days.index(date)
        except ValueError:
            return pd.Series(dtype=float)

        start_idx = max(0, idx - lookback_days + 1)
        relevant_days = trading_days[start_idx : idx + 1]
        rows = []
        for day in relevant_days:
            price_data = self.prefetcher.get_cached_prices(ticker, day)
            if price_data and price_data.get("close", 0) > 0:
                rows.append((pd.to_datetime(day), float(price_data["close"])))
        if not rows:
            return pd.Series(dtype=float)
        return pd.Series([value for _, value in rows], index=[ts for ts, _ in rows], dtype=float)

    def _build_market_proxy_series(self, date: str) -> pd.Series:
        return self._build_equal_weight_benchmark_curve(self.get_trading_days()).loc[:pd.to_datetime(date)]

    def _compute_vol_scaling(self, ticker: str, date: str) -> float:
        vol_window = int(self.momentum_config["vol_window"])
        prices = self._load_price_series(ticker, date, lookback_days=max(vol_window + 1, 30))
        if len(prices) < vol_window + 1:
            return 1.0

        realized_vol = prices.pct_change().dropna().rolling(window=vol_window).std().iloc[-1] * math.sqrt(252)
        if pd.isna(realized_vol) or realized_vol <= 0:
            return 1.0

        target_vol = float(self.momentum_config["target_vol"])
        scaling = target_vol / float(realized_vol)
        scaling = min(float(self.momentum_config["max_scaling"]), scaling)
        scaling = max(float(self.momentum_config["min_scaling"]), scaling)
        return scaling

    def _market_crash_breaker_multiplier(self, date: str) -> float:
        crash_lookback = int(self.momentum_config["crash_lookback_days"])
        market_ma_window = int(self.momentum_config["market_ma_window"])
        market_proxy = self._build_market_proxy_series(date)
        if len(market_proxy) < max(crash_lookback + 1, market_ma_window):
            return 1.0

        market_5d_return = market_proxy.iloc[-1] / market_proxy.iloc[-(crash_lookback + 1)] - 1
        market_ma = market_proxy.rolling(window=market_ma_window).mean().iloc[-1]
        if (
            market_5d_return > float(self.momentum_config["crash_return_threshold"])
            and market_proxy.iloc[-1] < market_ma
        ):
            self._crash_breaker_trigger_count += 1
            return float(self.momentum_config["crash_exposure_multiplier"])
        return 1.0

    @staticmethod
    def _momentum_signal_strength(signal: Any) -> float:
        if hasattr(signal, "signal"):
            raw = str(signal.signal).upper()
        elif isinstance(signal, dict):
            raw = str(signal.get("signal", "NEUTRAL")).upper()
        else:
            raw = str(signal).upper()

        if "BULLISH" in raw:
            return 1.0
        if "BEARISH" in raw:
            return 0.0
        return 0.5

    def _generate_llm_decisions(self, date: str, prices: Dict[str, float]) -> Dict[str, Dict]:
        if not (self.portfolio_mode and self.portfolio_allocator and self.workflow_adapter):
            return super()._generate_llm_decisions(date, prices)

        try:
            all_signals = self.workflow_adapter.collect_signals_only(trading_date=date, prices=prices)
            if not all_signals:
                return super()._generate_llm_decisions(date, prices)

            from backtest.portfolio_allocator import Portfolio as AllocatorPortfolio

            alloc_portfolio = AllocatorPortfolio(
                cashflow=self.current_portfolio["cashflow"],
                positions={
                    ticker: int(pos.get("shares", 0))
                    for ticker, pos in self.current_portfolio["positions"].items()
                },
            )

            base_targets = allocate_with_mandate(
                self.portfolio_allocator,
                signals=all_signals,
                current_portfolio=alloc_portfolio,
                prices=prices,
                trading_date=date,
                decision_memory=self.decision_memory[-5:] if self.decision_memory else None,
            )

            crash_multiplier = self._market_crash_breaker_multiplier(date)
            self._exposure_multipliers.append(crash_multiplier)
            self._momentum_days += 1

            adjusted_targets: Dict[str, float] = {}
            for ticker in prices:
                base_weight = float(base_targets.get(ticker, 0.0) or 0.0)
                signal_bundle = all_signals.get(ticker, {})
                summary = signal_bundle.get("summary", {})
                bullish_count = float(summary.get("bullish_count", 0) or 0)
                bearish_count = float(summary.get("bearish_count", 0) or 0)
                if bullish_count + bearish_count > 0:
                    sentiment_bias = bullish_count / (bullish_count + bearish_count)
                else:
                    sentiment_bias = 0.5

                vol_scaling = self._compute_vol_scaling(ticker, date)
                if abs(vol_scaling - 1.0) > 1e-9:
                    self._vol_scaling_events += 1

                adjusted = base_weight * vol_scaling * crash_multiplier * sentiment_bias
                adjusted_targets[ticker] = max(adjusted, 0.0)

            total = sum(adjusted_targets.values())
            if total > 1.0 and total > 0:
                adjusted_targets = {ticker: weight / total for ticker, weight in adjusted_targets.items()}

            decisions = self._convert_targets_to_trades(adjusted_targets, prices, date)
            for ticker, dec in decisions.items():
                self.decision_memory.append(
                    {
                        "trading_date": date,
                        "ticker": ticker,
                        "action": dec.get("action", "HOLD"),
                        "shares": dec.get("shares", 0),
                        "price": prices.get(ticker, 0),
                    }
                )
                dec["_applied"] = True
            return decisions

        except Exception as exc:
            logger.error(f"Behavioral momentum decision path failed for {date}: {exc}")
            return super()._generate_llm_decisions(date, prices)

    def _momentum_behavior_metrics(self) -> Dict[str, float]:
        days = max(self._momentum_days, 1)
        return {
            "vol_scaling_activation_rate": round(self._vol_scaling_events / days, 4),
            "crash_breaker_trigger_count": float(self._crash_breaker_trigger_count),
            "avg_momentum_exposure_multiplier": round(
                sum(self._exposure_multipliers) / len(self._exposure_multipliers), 4
            ) if self._exposure_multipliers else 1.0,
        }

    def finalize_run(
        self,
        trading_days: List[str],
        run_id: Optional[str] = None,
        generate_report: bool = True,
        errors: Optional[List[str]] = None,
        token_stats_override: Optional[Dict[str, Any]] = None,
    ) -> BacktestResult:
        result = super().finalize_run(
            trading_days=trading_days,
            run_id=run_id,
            generate_report=False,
            errors=errors,
            token_stats_override=token_stats_override,
        )
        result.metrics.update(self._momentum_behavior_metrics())
        result.config.setdefault("momentum", dict(self.momentum_config))

        if generate_report:
            try:
                report_paths = self.reporter.generate_full_report(
                    result,
                    result.run_id,
                    token_stats_override=token_stats_override,
                )
                logger.info(f"Reports generated: {report_paths}")
            except Exception as exc:
                logger.error(f"Report generation failed: {exc}")
                result.errors.append(f"Report error: {str(exc)}")

        return result
