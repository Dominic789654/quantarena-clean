"""
Macro Tactical Backtest Engine
==============================

Top-down tactical allocation engine built as a macro-aware overlay on top
of the existing FOF backtest engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd
from loguru import logger

from apis.router import Router, resolve_api_source
from backtest.fof_engine import FOFBacktestEngine

if TYPE_CHECKING:
    from backtest.providers import MacroProvider


class MacroTacticalBacktestEngine(FOFBacktestEngine):
    """Macro-aware tactical allocation engine built on the FOF sleeve stack."""

    DEFAULT_TACTICAL_CONFIG: Dict[str, Any] = {
        "short_window": 20,
        "crash_window": 5,
        "long_ma_window": 60,
        "bull_return_threshold": 0.03,
        "bear_return_threshold": -0.05,
        "volatile_rally_threshold": 0.04,
        "high_vol_threshold": 0.25,
        "inflation_hot_threshold": 3.5,
        "unemployment_bad_threshold": 6.0,
        "rate_tight_threshold": 4.5,
    }

    def __init__(self, *args, macro_provider: Optional[MacroProvider] = None, **kwargs):
        kwargs["personality"] = "macro_tactical"
        super().__init__(*args, **kwargs)
        self.personality = "macro_tactical"
        self.macro_provider = macro_provider
        cfg = dict(self.DEFAULT_TACTICAL_CONFIG)
        cfg.update(dict((self.config or {}).get("macro_tactical", {}) or {}))
        self.macro_tactical_config = cfg
        self.config["personality"] = "macro_tactical"
        self.config["macro_tactical"] = dict(cfg)
        logger.info(f"MacroTacticalBacktestEngine initialized with config={self.macro_tactical_config}")

    def _build_market_proxy_series(self, date: str) -> pd.Series:
        return self._build_equal_weight_benchmark_curve(self.get_trading_days()).loc[:pd.to_datetime(date)]

    @staticmethod
    def _safe_numeric(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip().replace(",", "")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _extract_indicator_value(self, payload: Any) -> Optional[float]:
        if payload is None:
            return None
        if isinstance(payload, (int, float, str)):
            return self._safe_numeric(payload)
        if isinstance(payload, dict):
            preferred_keys = [
                "value",
                "val",
                "nt_val",
                "cpi_yoy",
                "unemployment_rate",
                "current",
            ]
            for key in preferred_keys:
                if key in payload:
                    numeric = self._safe_numeric(payload[key])
                    if numeric is not None:
                        return numeric
            for key, value in payload.items():
                if any(token in str(key).lower() for token in ("date", "time", "period")):
                    continue
                numeric = self._safe_numeric(value)
                if numeric is not None:
                    return numeric
        return None

    def _normalize_rate(self, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if abs(value) <= 1.0:
            return value * 100
        return value

    def _fetch_macro_snapshot(self) -> Dict[str, Optional[float]]:
        try:
            if self.macro_provider is not None:
                indicators = self.macro_provider.get_economic_indicators(self.market)
            else:
                api_source = resolve_api_source(self.market, self.api_source_config)
                router = Router(api_source)
                indicators = (
                    router.get_cn_economic_indicators()
                    if self.market == "cn"
                    else router.get_us_economic_indicators()
                )
        except Exception as exc:
            logger.warning(f"Macro tactical engine failed to fetch indicators: {exc}")
            return {"cpi": None, "unemployment": None, "policy_rate": None}

        cpi_payload = getattr(indicators, "cpi", None)
        unemployment_payload = getattr(indicators, "unemployment", None) or getattr(indicators, "unemployment_rate", None)
        rate_payload = getattr(indicators, "federal_funds_rate", None) or getattr(indicators, "loan_rate", None)

        return {
            "cpi": self._normalize_rate(self._extract_indicator_value(cpi_payload)),
            "unemployment": self._normalize_rate(self._extract_indicator_value(unemployment_payload)),
            "policy_rate": self._normalize_rate(self._extract_indicator_value(rate_payload)),
        }

    def _derive_macro_bias(self, snapshot: Dict[str, Optional[float]]) -> int:
        cfg = self.macro_tactical_config
        bias = 0
        cpi = snapshot.get("cpi")
        unemployment = snapshot.get("unemployment")
        policy_rate = snapshot.get("policy_rate")

        if cpi is not None and cpi > float(cfg["inflation_hot_threshold"]):
            bias -= 1
        elif cpi is not None and cpi < float(cfg["inflation_hot_threshold"]) - 1.0:
            bias += 1

        if unemployment is not None and unemployment > float(cfg["unemployment_bad_threshold"]):
            bias -= 1
        elif unemployment is not None and unemployment < float(cfg["unemployment_bad_threshold"]) - 1.0:
            bias += 1

        if policy_rate is not None and policy_rate > float(cfg["rate_tight_threshold"]):
            bias -= 1
        return bias

    def _derive_regime_from_market_proxy(self, date: str, macro_bias: int = 0) -> Dict[str, Any]:
        cfg = self.macro_tactical_config
        market_proxy = self._build_market_proxy_series(date)
        if len(market_proxy) < max(int(cfg["long_ma_window"]), int(cfg["short_window"]) + 1):
            return {
                "regime": "neutral",
                "market_short_return": 0.0,
                "market_crash_return": 0.0,
                "market_volatility": 0.0,
            }

        short_window = int(cfg["short_window"])
        crash_window = int(cfg["crash_window"])
        long_ma_window = int(cfg["long_ma_window"])

        market_short_return = market_proxy.iloc[-1] / market_proxy.iloc[-(short_window + 1)] - 1
        market_crash_return = market_proxy.iloc[-1] / market_proxy.iloc[-(crash_window + 1)] - 1
        market_ma = market_proxy.rolling(window=long_ma_window).mean().iloc[-1]
        market_volatility = market_proxy.pct_change().dropna().rolling(window=short_window).std().iloc[-1] * (252 ** 0.5)

        regime = "neutral"
        if (
            market_crash_return > float(cfg["volatile_rally_threshold"])
            and market_proxy.iloc[-1] < market_ma
        ) or market_volatility > float(cfg["high_vol_threshold"]):
            regime = "volatile"
        elif market_short_return <= float(cfg["bear_return_threshold"]):
            regime = "bear"
        elif market_short_return >= float(cfg["bull_return_threshold"]) and market_proxy.iloc[-1] >= market_ma:
            regime = "bull"

        if macro_bias <= -2:
            if regime == "bull":
                regime = "neutral"
            elif regime == "neutral":
                regime = "bear"
        elif macro_bias >= 2:
            if regime == "bear":
                regime = "neutral"
            elif regime == "neutral":
                regime = "bull"

        return {
            "regime": regime,
            "market_short_return": round(float(market_short_return), 4),
            "market_crash_return": round(float(market_crash_return), 4),
            "market_volatility": round(float(market_volatility), 4),
        }

    def _build_market_context(self, enhanced_signals: Dict[str, Any]) -> Dict[str, Any]:
        context = dict(super()._build_market_context(enhanced_signals))
        latest_date = ""
        for payload in (enhanced_signals or {}).values():
            latest_date = str(payload.get("trading_date", "")) or latest_date
        if not latest_date and self.tracker.snapshots:
            latest_date = self.tracker.snapshots[-1].date
        if not latest_date:
            return context

        macro_snapshot = self._fetch_macro_snapshot()
        macro_bias = self._derive_macro_bias(macro_snapshot)
        regime_payload = self._derive_regime_from_market_proxy(latest_date, macro_bias=macro_bias)
        context.update(regime_payload)
        context["macro_snapshot"] = macro_snapshot
        context["macro_bias"] = macro_bias
        return context
