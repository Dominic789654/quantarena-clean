"""Structure contract for the matched CN/US experiment universes.

The README claims 40 matched tickers across two 20-name windows; these tests
pin that claim to the actual config files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CONFIG_DIR = Path(__file__).parent.parent / "deepfund" / "src" / "config"

EXPECTED_SECTORS = ["financials", "consumer", "technology", "healthcare", "industrials"]
EXPECTED_BUCKETS = {"large_value", "large_growth", "mid_value", "mid_growth"}

CN_EXPECTED = {
    "financials": ["600036", "601166", "000001", "002142"],
    "consumer": ["600519", "000858", "600887", "603288"],
    "technology": ["300750", "002415", "603986", "688111"],
    "healthcare": ["300760", "600276", "300347", "300122"],
    "industrials": ["601899", "600309", "601100", "002353"],
}

US_EXPECTED = {
    "financials": ["JPM", "GS", "PNC", "IBKR"],
    "consumer": ["KO", "AMZN", "KHC", "SBUX"],
    "technology": ["CSCO", "MSFT", "HPQ", "PANW"],
    "healthcare": ["JNJ", "LLY", "BAX", "VRTX"],
    "industrials": ["HON", "CAT", "EMR", "GE"],
}


def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


def _sectors(config: dict) -> dict:
    return {s["name"]: s["stocks"] for s in config["experiment_universe"]["sectors"]}


@pytest.mark.parametrize(
    "filename,market,expected",
    [
        ("ashare_experiment_universe.yaml", "cn", CN_EXPECTED),
        ("us_experiment_universe.yaml", "us", US_EXPECTED),
    ],
)
def test_universe_structure_and_tickers(filename, market, expected):
    config = _load(filename)
    assert config["market"] == market

    sectors = _sectors(config)
    assert list(sectors) == EXPECTED_SECTORS

    all_tickers = []
    for sector_name, stocks in sectors.items():
        assert len(stocks) == 4, f"{sector_name} must hold exactly 4 names"
        assert {s["bucket"] for s in stocks} == EXPECTED_BUCKETS, (
            f"{sector_name} must cover all four style buckets exactly once"
        )
        assert [s["ticker"] for s in stocks] == expected[sector_name]
        for stock in stocks:
            assert stock.get("label"), f"{stock['ticker']} is missing a label"
        all_tickers.extend(s["ticker"] for s in stocks)

    assert len(all_tickers) == 20
    assert len(set(all_tickers)) == 20, "tickers must be unique"


def test_universes_are_matched_across_markets():
    """Same sectors, same bucket layout, and disjoint 20-name windows."""
    cn = _sectors(_load("ashare_experiment_universe.yaml"))
    us = _sectors(_load("us_experiment_universe.yaml"))

    assert list(cn) == list(us)
    for sector in cn:
        cn_buckets = [s["bucket"] for s in cn[sector]]
        us_buckets = [s["bucket"] for s in us[sector]]
        assert cn_buckets == us_buckets, f"{sector} bucket order must match across markets"

    cn_tickers = {s["ticker"] for stocks in cn.values() for s in stocks}
    us_tickers = {s["ticker"] for stocks in us.values() for s in stocks}
    assert len(cn_tickers | us_tickers) == 40
