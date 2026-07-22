"""Tests for Router alt-data accessors (SEC EDGAR and ApeWisdom)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from deepfund.src.apis import router as router_mod
from deepfund.src.apis.router import APISource, Router


@pytest.fixture
def fmp_router(monkeypatch):
    """A Router on the FMP source with the primary API stubbed out."""
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "QuantArenaTest/1.0 (test@example.com)")
    return Router(APISource.FMP)


def test_router_lazy_inits_secedgar(fmp_router, monkeypatch):
    secedgar_instance = Mock()
    secedgar_cls = Mock(return_value=secedgar_instance)
    monkeypatch.setattr(router_mod, "SECEdgarAPI", secedgar_cls)

    assert fmp_router._secedgar_api is None

    trading_date = datetime(2026, 7, 1)
    fmp_router.get_us_institutional_filings("berkshire_hathaway", trading_date=trading_date)
    fmp_router.get_us_insider_filings("NVDA", trading_date=trading_date, days_back=30, limit=5)

    secedgar_cls.assert_called_once()
    secedgar_instance.get_institutional_filings.assert_called_once_with(
        "berkshire_hathaway", forms=("13F-HR",), trading_date=trading_date, limit=10
    )
    secedgar_instance.get_insider_filings.assert_called_once_with(
        "NVDA", trading_date=trading_date, days_back=30, limit=5
    )


def test_router_lazy_inits_apewisdom(fmp_router, monkeypatch):
    ape_instance = Mock()
    ape_cls = Mock(return_value=ape_instance)
    monkeypatch.setattr(router_mod, "ApeWisdomAPI", ape_cls)

    assert fmp_router._apewisdom_api is None

    fmp_router.get_us_social_trending(limit=10)
    fmp_router.get_us_social_ticker_mentions("MU")

    ape_cls.assert_called_once()
    ape_instance.get_trending.assert_called_once_with(filter_key="wallstreetbets", limit=10)
    ape_instance.get_ticker_mentions.assert_called_once_with("MU", filter_key="wallstreetbets")


def test_alt_data_does_not_touch_primary_source(fmp_router, monkeypatch):
    """Alt-data accessors must not depend on the configured candle source."""
    ape_instance = Mock()
    monkeypatch.setattr(router_mod, "ApeWisdomAPI", Mock(return_value=ape_instance))
    fmp_router.api = Mock()

    fmp_router.get_us_social_trending()

    fmp_router.api.assert_not_called()
    assert not fmp_router.api.method_calls
