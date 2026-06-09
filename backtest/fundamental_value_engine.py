"""
Fundamental Value Backtest Engine
=================================

Lightweight value-oriented backtest engine that applies explicit
EV/EBITDA and F-Score Lite filters before delegating allocation to the
existing LLM portfolio workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

from apis.router import Router, resolve_api_source
from backtest.engine import BacktestEngine, BacktestResult
from backtest.mandate_interface import allocate_with_mandate


@dataclass
class ValueFilterResult:
    """Serializable result of the value filter for one ticker."""

    passed: bool
    ev_to_ebitda: Optional[float]
    roa: Optional[float]
    operating_cash_flow: Optional[float]
    current_ratio: Optional[float]
    lite_score: int
    max_score: int
    normalized_score: float
    reasons: List[str]


class FundamentalValueBacktestEngine(BacktestEngine):
    """Backtest engine for the scaffolded Fundamental Value paradigm."""

    DEFAULT_FILTER_CONFIG: Dict[str, Any] = {
        "max_ev_to_ebitda": 15.0,
        "min_fscore_lite": 3,
        "require_positive_roa": True,
        "require_positive_ocf": True,
        "min_current_ratio": 1.0,
        "require_positive_profit_margin": False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = dict(self.DEFAULT_FILTER_CONFIG)
        cfg.update(dict((self.config or {}).get("value_filter", {}) or {}))
        self.value_filter_config = cfg
        self._fundamentals_cache: Dict[str, Any] = {}
        self._value_filter_history: List[Dict[str, Any]] = []
        logger.info(f"FundamentalValueBacktestEngine initialized with filter config={self.value_filter_config}")

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip()
        if not raw or raw.upper() in {"N/A", "NONE", "NULL", "NAN", "-"}:
            return None
        raw = raw.replace(",", "")
        try:
            return float(raw)
        except ValueError:
            return None

    def _get_router(self) -> Router:
        api_source = resolve_api_source(self.market, self.api_source_config)
        return Router(api_source)

    def _get_fundamentals(self, ticker: str):
        if ticker in self._fundamentals_cache:
            return self._fundamentals_cache[ticker]

        router = self._get_router()
        if self.market == "cn":
            fundamentals = router.get_cn_stock_fundamentals(ticker)
        else:
            fundamentals = router.get_us_stock_fundamentals(ticker)
        self._fundamentals_cache[ticker] = fundamentals
        return fundamentals

    def _evaluate_value_filter(self, fundamentals: Any) -> ValueFilterResult:
        cfg = self.value_filter_config

        ev_to_ebitda = self._safe_float(getattr(fundamentals, "ev_to_ebitda", None))
        roa = self._safe_float(
            getattr(fundamentals, "return_on_assets_ttm", None) or getattr(fundamentals, "roa", None)
        )
        operating_cash_flow = self._safe_float(getattr(fundamentals, "operating_cash_flow", None))
        current_ratio = self._safe_float(getattr(fundamentals, "current_ratio", None))
        profit_margin = self._safe_float(
            getattr(fundamentals, "profit_margin", None) or getattr(fundamentals, "net_profit_margin", None)
        )

        reasons: List[str] = []

        ev_pass = ev_to_ebitda is not None and ev_to_ebitda < float(cfg["max_ev_to_ebitda"])
        if not ev_pass:
            reasons.append("ev_to_ebitda")

        checks = []
        if cfg.get("require_positive_roa", True):
            checks.append(roa is not None and roa > 0)
            if not checks[-1]:
                reasons.append("roa")
        if cfg.get("require_positive_ocf", True):
            checks.append(operating_cash_flow is not None and operating_cash_flow > 0)
            if not checks[-1]:
                reasons.append("operating_cash_flow")
        checks.append(current_ratio is not None and current_ratio > float(cfg["min_current_ratio"]))
        if not checks[-1]:
            reasons.append("current_ratio")
        if cfg.get("require_positive_profit_margin", False):
            checks.append(profit_margin is not None and profit_margin > 0)
            if not checks[-1]:
                reasons.append("profit_margin")

        lite_score = sum(1 for item in checks if item)
        max_score = max(len(checks), 1)
        normalized = lite_score / max_score
        passed = ev_pass and lite_score >= int(cfg["min_fscore_lite"])

        return ValueFilterResult(
            passed=passed,
            ev_to_ebitda=ev_to_ebitda,
            roa=roa,
            operating_cash_flow=operating_cash_flow,
            current_ratio=current_ratio,
            lite_score=lite_score,
            max_score=max_score,
            normalized_score=normalized,
            reasons=reasons,
        )

    def _record_value_filter_snapshot(self, date: str, filter_results: Dict[str, ValueFilterResult]) -> None:
        checked = len(filter_results)
        passed = sum(1 for result in filter_results.values() if result.passed)
        normalized_scores = [result.normalized_score for result in filter_results.values()]
        self._value_filter_history.append(
            {
                "date": date,
                "checked": checked,
                "passed": passed,
                "avg_normalized_score": sum(normalized_scores) / len(normalized_scores) if normalized_scores else 0.0,
            }
        )

    def _value_behavior_metrics(self) -> Dict[str, float]:
        if not self._value_filter_history:
            return {
                "value_filter_pass_rate": 0.0,
                "value_consistency_score": 0.0,
            }

        checked = sum(item["checked"] for item in self._value_filter_history)
        passed = sum(item["passed"] for item in self._value_filter_history)
        avg_score = (
            sum(item["avg_normalized_score"] for item in self._value_filter_history) / len(self._value_filter_history)
        )
        return {
            "value_filter_pass_rate": round((passed / checked * 100) if checked else 0.0, 2),
            "value_consistency_score": round(avg_score, 4),
        }

    def _generate_value_filtered_decisions_from_signals(
        self,
        *,
        date: str,
        prices: Dict[str, float],
        all_signals: Dict[str, Any],
    ) -> Dict[str, Dict]:
        filter_results: Dict[str, ValueFilterResult] = {}
        for ticker in prices:
            try:
                fundamentals = self._get_fundamentals(ticker)
                filter_results[ticker] = self._evaluate_value_filter(fundamentals)
            except Exception as exc:
                logger.warning(f"Fundamental value filter failed for {ticker}: {exc}")
                filter_results[ticker] = ValueFilterResult(
                    passed=False,
                    ev_to_ebitda=None,
                    roa=None,
                    operating_cash_flow=None,
                    current_ratio=None,
                    lite_score=0,
                    max_score=3,
                    normalized_score=0.0,
                    reasons=["fundamentals_fetch"],
                )

        self._record_value_filter_snapshot(date, filter_results)
        passed_signals = {
            ticker: signal
            for ticker, signal in all_signals.items()
            if filter_results.get(ticker) and filter_results[ticker].passed
        }

        from backtest.portfolio_allocator import Portfolio as AllocatorPortfolio

        alloc_portfolio = AllocatorPortfolio(
            cashflow=self.current_portfolio["cashflow"],
            positions={
                ticker: int(pos.get("shares", 0))
                for ticker, pos in self.current_portfolio["positions"].items()
            },
        )

        if passed_signals:
            target_positions = allocate_with_mandate(
                self.portfolio_allocator,
                signals=passed_signals,
                current_portfolio=alloc_portfolio,
                prices=prices,
                trading_date=date,
                decision_memory=self.decision_memory[-5:] if self.decision_memory else None,
            )
        else:
            target_positions = {}

        for ticker in prices:
            if ticker not in target_positions:
                target_positions[ticker] = 0.0

        decisions = self._convert_targets_to_trades(target_positions, prices, date)

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

    def _generate_llm_decisions(self, date: str, prices: Dict[str, float]) -> Dict[str, Dict]:
        if not (self.portfolio_mode and self.portfolio_allocator and self.workflow_adapter):
            return super()._generate_llm_decisions(date, prices)

        try:
            all_signals = self.workflow_adapter.collect_signals_only(trading_date=date, prices=prices)
            if not all_signals:
                logger.warning("No signals collected in FundamentalValue engine; falling back to HOLD.")
                return super()._generate_llm_decisions(date, prices)

            return self._generate_value_filtered_decisions_from_signals(
                date=date,
                prices=prices,
                all_signals=all_signals,
            )

        except Exception as exc:
            logger.error(f"Fundamental value decision path failed for {date}: {exc}")
            return super()._generate_llm_decisions(date, prices)

    def _generate_llm_decisions_with_precollected_signals(
        self,
        date: str,
        prices: Dict[str, float],
        enhanced_signals: Dict[str, Any],
        priority_order: Optional[List[str]] = None,
    ) -> Dict[str, Dict]:
        if not (self.portfolio_mode and self.portfolio_allocator and self.workflow_adapter):
            return super()._generate_llm_decisions_with_precollected_signals(
                date,
                prices,
                enhanced_signals,
                priority_order=priority_order,
            )

        try:
            return self._generate_value_filtered_decisions_from_signals(
                date=date,
                prices=prices,
                all_signals=enhanced_signals,
            )
        except Exception as exc:
            logger.error(f"Fundamental value shared-signal decision path failed for {date}: {exc}")
            return super()._generate_llm_decisions_with_precollected_signals(
                date,
                prices,
                enhanced_signals,
                priority_order=priority_order,
            )

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
        result.metrics.update(self._value_behavior_metrics())
        result.config.setdefault("value_filter", dict(self.value_filter_config))

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
