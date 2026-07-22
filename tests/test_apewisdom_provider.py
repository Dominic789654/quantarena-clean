"""Unit tests for the ApeWisdom provider (Reddit retail-sentiment mentions)."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from deepfund.src.apis.apewisdom.api import ApeWisdomAPI
from deepfund.src.apis.apewisdom.api_model import SocialMention


PAGE1_FIXTURE = {
    "count": 626,
    "pages": 2,
    "current_page": 1,
    "results": [
        {
            "rank": 1,
            "ticker": "MU",
            "name": "Micron Technology",
            "mentions": 474,
            "upvotes": 2441,
            "rank_24h_ago": 2,
            "mentions_24h_ago": 237,
        },
        {
            "rank": 2,
            "ticker": "spy",
            "name": "SPDR S&P 500 ETF Trust",
            "mentions": "262",
            "upvotes": None,
            "rank_24h_ago": None,
            "mentions_24h_ago": "",
        },
        {
            # Malformed row: missing required rank -> should be skipped.
            "ticker": "BROKEN",
        },
    ],
}

PAGE2_FIXTURE = {
    "count": 626,
    "pages": 2,
    "current_page": 2,
    "results": [
        {
            "rank": 101,
            "ticker": "GME",
            "name": "GameStop",
            "mentions": 12,
            "upvotes": 30,
            "rank_24h_ago": 99,
            "mentions_24h_ago": 20,
        },
    ],
}


def _make_api() -> ApeWisdomAPI:
    api = ApeWisdomAPI()
    api.min_request_interval = 0.0
    return api


def _mock_response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status = Mock()
    response.text = "mock-body"
    return response


@pytest.fixture(autouse=True)
def clear_apewisdom_cache():
    ApeWisdomAPI.clear_cache()
    yield
    ApeWisdomAPI.clear_cache()


def test_get_trending_parses_and_normalizes():
    api = _make_api()
    api.session.get = Mock(return_value=_mock_response(PAGE1_FIXTURE))

    mentions = api.get_trending()

    assert all(isinstance(m, SocialMention) for m in mentions)
    # Malformed row is skipped, valid rows survive.
    assert [m.ticker for m in mentions] == ["MU", "SPY"]
    assert mentions[0].mentions == 474
    assert mentions[0].mentions_change_24h == 474 - 237
    # String/None numerics are normalized.
    assert mentions[1].mentions == 262
    assert mentions[1].upvotes == 0
    assert mentions[1].mentions_24h_ago is None
    assert mentions[1].mentions_change_24h is None


def test_get_trending_respects_limit():
    api = _make_api()
    api.session.get = Mock(return_value=_mock_response(PAGE1_FIXTURE))

    mentions = api.get_trending(limit=1)

    assert len(mentions) == 1
    assert mentions[0].ticker == "MU"


def test_trending_page_is_cached():
    api = _make_api()
    api.session.get = Mock(return_value=_mock_response(PAGE1_FIXTURE))

    api.get_trending()
    api.get_trending()

    assert api.session.get.call_count == 1


def test_get_ticker_mentions_found_on_first_page():
    api = _make_api()
    api.session.get = Mock(return_value=_mock_response(PAGE1_FIXTURE))

    mention = api.get_ticker_mentions("mu")

    assert mention is not None
    assert mention.ticker == "MU"
    assert mention.rank == 1
    assert api.session.get.call_count == 1


def test_get_ticker_mentions_scans_pages():
    api = _make_api()
    api.session.get = Mock(side_effect=[
        _mock_response(PAGE1_FIXTURE),
        _mock_response(PAGE2_FIXTURE),
    ])

    mention = api.get_ticker_mentions("GME")

    assert mention is not None
    assert mention.rank == 101
    assert api.session.get.call_count == 2


def test_get_ticker_mentions_not_found_stops_at_last_page():
    api = _make_api()
    api.session.get = Mock(side_effect=[
        _mock_response(PAGE1_FIXTURE),
        _mock_response(PAGE2_FIXTURE),
    ])

    mention = api.get_ticker_mentions("ZZZZ", max_pages=10)

    assert mention is None
    # Fixture reports pages=2, so scanning stops there despite max_pages=10.
    assert api.session.get.call_count == 2


def test_request_retries_on_throttle(monkeypatch):
    api = _make_api()
    monkeypatch.setattr("time.sleep", lambda *_: None)
    api.session.get = Mock(side_effect=[
        _mock_response({}, status_code=429),
        _mock_response(PAGE1_FIXTURE),
    ])

    mentions = api.get_trending()

    assert api.session.get.call_count == 2
    assert len(mentions) == 2


def test_request_raises_after_max_retries(monkeypatch):
    api = _make_api()
    monkeypatch.setattr("time.sleep", lambda *_: None)
    api.session.get = Mock(return_value=_mock_response({}, status_code=503))

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        api.get_trending()


def test_request_propagates_http_error():
    api = _make_api()
    response = _mock_response({}, status_code=500)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    api.session.get = Mock(return_value=response)

    with pytest.raises(requests.exceptions.HTTPError):
        api.get_trending()
