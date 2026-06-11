"""Opt-in live provider smoke checks for QuantArena development."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from shared.config.provider_routing import preferred_us_data_provider
from shared.utils.path_manager import setup_paths


PROVIDER_KEY_ENV: dict[str, str] = {
    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
    "fmp": "FMP_API_KEY",
    "tushare": "TUSHARE_API_KEY",
}
PROVIDER_ALIASES: dict[str, str] = {
    "alpha": "alpha_vantage",
    "alphavantage": "alpha_vantage",
    "alpha_vantage": "alpha_vantage",
    "tushare": "tushare",
    "fmp": "fmp",
    "financialmodelingprep": "fmp",
    "yfinance": "yfinance",
    "yf": "yfinance",
}


@dataclass(frozen=True)
class ProviderSmokeResult:
    """Result payload for a provider smoke check."""

    ok: bool
    market: str
    provider: str
    ticker: str
    date: str
    skipped: bool = False
    reason: str | None = None
    rows: int | None = None
    columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "market": self.market,
            "provider": self.provider,
            "ticker": self.ticker,
            "date": self.date,
            "skipped": self.skipped,
            "reason": self.reason,
            "rows": self.rows,
            "columns": self.columns,
        }


def run_provider_smoke_check(
    *,
    market: str,
    provider: str | None = None,
    ticker: str | None = None,
    date: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProviderSmokeResult:
    """Run a minimal live daily-candle provider check or skip cleanly without credentials."""
    setup_paths()

    normalized_market = (market or "us").strip().lower()
    default_ticker = "600519" if normalized_market == "cn" else "AAPL"
    resolved_ticker = ticker or default_ticker
    resolved_date = date or datetime.utcnow().strftime("%Y-%m-%d")
    env_map = os.environ if env is None else env
    source, source_error = _resolve_smoke_source(
        market=normalized_market,
        provider=provider,
    )

    if source_error:
        return ProviderSmokeResult(
            ok=False,
            market=normalized_market,
            provider=source or str(provider or ""),
            ticker=resolved_ticker,
            date=resolved_date,
            reason=source_error,
        )

    missing_key = _missing_key_reason(source, env_map)
    if missing_key:
        return ProviderSmokeResult(
            ok=True,
            market=normalized_market,
            provider=source,
            ticker=resolved_ticker,
            date=resolved_date,
            skipped=True,
            reason=missing_key,
        )

    try:
        trading_date = datetime.strptime(resolved_date, "%Y-%m-%d")
    except ValueError:
        return ProviderSmokeResult(
            ok=False,
            market=normalized_market,
            provider=source,
            ticker=resolved_ticker,
            date=resolved_date,
            reason="date must use YYYY-MM-DD format",
        )

    try:
        from apis.router import APISource, Router

        router = Router(source)
        if normalized_market == "cn":
            frame = router.get_cn_stock_daily_candles_df(resolved_ticker, trading_date)
        elif source in {APISource.FMP, APISource.ALPHA_VANTAGE}:
            frame = router.get_us_stock_daily_candles_df(resolved_ticker, trading_date)
        else:
            return ProviderSmokeResult(
                ok=False,
                market=normalized_market,
                provider=source,
                ticker=resolved_ticker,
                date=resolved_date,
                reason=f"provider {source} is not supported for market {normalized_market}",
            )
    except Exception as exc:
        return ProviderSmokeResult(
            ok=False,
            market=normalized_market,
            provider=source,
            ticker=resolved_ticker,
            date=resolved_date,
            reason=_safe_exception_reason(exc, env_map),
        )

    rows = int(len(frame)) if frame is not None else 0
    columns = [str(col) for col in getattr(frame, "columns", [])]
    return ProviderSmokeResult(
        ok=rows > 0,
        market=normalized_market,
        provider=source,
        ticker=resolved_ticker,
        date=resolved_date,
        rows=rows,
        columns=columns,
        reason=None if rows > 0 else "provider returned no candle rows",
    )


def _missing_key_reason(source: str, env: Mapping[str, str]) -> str | None:
    key_env = PROVIDER_KEY_ENV.get(source)
    if key_env and not str(env.get(key_env, "")).strip():
        return f"missing credential: {key_env}"
    return None


def _resolve_smoke_source(
    *,
    market: str,
    provider: str | None,
) -> tuple[str, str | None]:
    if provider:
        try:
            source = _provider_from_string(provider)
        except ValueError:
            return str(provider), f"invalid provider: {provider}"
    else:
        source = (
            "tushare"
            if market == "cn"
            else preferred_us_data_provider(env_override=os.environ.get("DEEPFUND_US_API_SOURCE", ""))
        )

    if market == "cn":
        if source != "tushare":
            return source, f"provider {source} is not supported for market cn"
        return source, None

    if market == "us":
        if source not in {"fmp", "alpha_vantage"}:
            return source, f"provider {source} is not supported for market us"
        return source, None

    return source, f"unsupported market: {market}"


def _provider_from_string(value: str | None) -> str:
    key = (value or "").strip().lower()
    if key in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[key]
    raise ValueError(f"Invalid API source: {value}")


def _safe_exception_reason(exc: Exception, env: Mapping[str, str]) -> str:
    message = str(exc)
    message = re.sub(r"(?i)(apikey=)[^&\s]+", r"\1<redacted>", message)
    message = re.sub(r"(?i)(api_key=)[^&\s]+", r"\1<redacted>", message)
    message = re.sub(r"(?i)(token=)[^&\s]+", r"\1<redacted>", message)
    for value in env.values():
        secret = str(value or "").strip()
        if len(secret) >= 4:
            message = message.replace(secret, "<redacted>")
    return f"{type(exc).__name__}: {message}"
