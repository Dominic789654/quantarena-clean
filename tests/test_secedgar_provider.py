"""Unit tests for the SEC EDGAR provider (13F institutional + Form 4 insider filings)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest
import requests

from deepfund.src.apis.secedgar.api import SECEdgarAPI, KNOWN_INSTITUTIONS
from deepfund.src.apis.secedgar.api_model import InsiderFiling, InstitutionalFiling


SUBMISSIONS_FIXTURE = {
    "cik": "0001067983",
    "filings": {
        "recent": {
            "form": ["4", "13F-HR", "8-K", "13F-HR", "13F-HR"],
            "filingDate": ["2026-06-01", "2026-05-15", "2026-04-30", "2026-02-14", "2025-11-14"],
            "accessionNo": [
                "0001067983-26-000050",
                "0000950123-26-005555",
                "0001067983-26-000040",
                "0000950123-26-001111",
                "0000950123-25-009999",
            ],
            "primaryDocument": ["a.xml", "b.xml", "c.htm", "d.xml", "e.xml"],
        }
    },
}

FORM4_SEARCH_FIXTURE = {
    "hits": {
        "total": {"value": 2},
        "hits": [
            {
                "_source": {
                    "ciks": ["0001045810"],
                    "display_names": ["HUANG JEN HSUN (CIK 0001234567)"],
                    "file_type": "4",
                    "file_date": "2026-07-01",
                    "adsh": "0001045810-26-000123",
                }
            },
            {
                "_source": {
                    "ciks": [],
                    "display_names": [],
                    "file_type": "4",
                    "file_date": "2026-06-20",
                    "adsh": "0001045810-26-000100",
                }
            },
        ],
    }
}


def _make_api(monkeypatch) -> SECEdgarAPI:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "QuantArenaTest/1.0 (test@example.com)")
    api = SECEdgarAPI()
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
def clear_secedgar_cache():
    SECEdgarAPI.clear_cache()
    yield
    SECEdgarAPI.clear_cache()


def test_missing_user_agent_raises(monkeypatch):
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    with pytest.raises(ValueError, match="SEC_EDGAR_USER_AGENT"):
        SECEdgarAPI()


def test_user_agent_header_is_set(monkeypatch):
    api = _make_api(monkeypatch)
    assert api.session.headers["User-Agent"] == "QuantArenaTest/1.0 (test@example.com)"


def test_normalize_cik_pads_and_validates():
    assert SECEdgarAPI.normalize_cik("1067983") == "0001067983"
    assert SECEdgarAPI.normalize_cik("0001067983") == "0001067983"
    with pytest.raises(ValueError):
        SECEdgarAPI.normalize_cik("not-a-cik")


def test_resolve_institution_alias():
    assert SECEdgarAPI.resolve_institution_cik("berkshire_hathaway") == KNOWN_INSTITUTIONS["berkshire_hathaway"]
    assert SECEdgarAPI.resolve_institution_cik("Berkshire Hathaway") == "0001067983"
    assert SECEdgarAPI.resolve_institution_cik("1067983") == "0001067983"


def test_get_institutional_filings_filters_forms(monkeypatch):
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))

    filings = api.get_institutional_filings("berkshire_hathaway")

    assert all(isinstance(f, InstitutionalFiling) for f in filings)
    assert [f.form for f in filings] == ["13F-HR", "13F-HR", "13F-HR"]
    assert filings[0].filing_date == "2026-05-15"
    assert filings[0].accession_no == "0000950123-26-005555"
    assert filings[0].filing_url == (
        "https://www.sec.gov/Archives/edgar/data/1067983/"
        "000095012326005555/0000950123-26-005555-index.htm"
    )


def test_get_institutional_filings_respects_trading_date(monkeypatch):
    """Backtests must not see filings published after the trading date."""
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))

    filings = api.get_institutional_filings(
        "1067983", trading_date=datetime(2026, 3, 1)
    )

    assert [f.filing_date for f in filings] == ["2026-02-14", "2025-11-14"]


def test_get_institutional_filings_respects_limit(monkeypatch):
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))

    filings = api.get_institutional_filings("1067983", limit=1)

    assert len(filings) == 1


def test_submissions_response_is_cached(monkeypatch):
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))

    api.get_institutional_filings("1067983")
    api.get_institutional_filings("1067983")

    assert api.session.get.call_count == 1


def test_get_insider_filings_parses_hits(monkeypatch):
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(FORM4_SEARCH_FIXTURE))

    filings = api.get_insider_filings("NVDA", trading_date=datetime(2026, 7, 10))

    assert all(isinstance(f, InsiderFiling) for f in filings)
    assert len(filings) == 2
    assert filings[0].ticker == "NVDA"
    assert filings[0].cik == "0001045810"
    assert filings[0].filer_names == ["HUANG JEN HSUN (CIK 0001234567)"]
    assert filings[0].filing_date == "2026-07-01"
    assert filings[0].filing_url is not None
    # Hit without CIK still parses, just without a URL.
    assert filings[1].cik is None
    assert filings[1].filing_url is None

    params = api.session.get.call_args.kwargs["params"]
    assert params["q"] == "NVDA"
    assert params["forms"] == "4"
    assert params["enddt"] == "2026-07-10"


def test_get_insider_filings_respects_limit(monkeypatch):
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(FORM4_SEARCH_FIXTURE))

    filings = api.get_insider_filings("NVDA", trading_date=datetime(2026, 7, 10), limit=1)

    assert len(filings) == 1


def test_request_retries_on_throttle(monkeypatch):
    api = _make_api(monkeypatch)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    throttled = _mock_response({}, status_code=429)
    ok = _mock_response(SUBMISSIONS_FIXTURE)
    api.session.get = Mock(side_effect=[throttled, ok])

    filings = api.get_institutional_filings("1067983")

    assert api.session.get.call_count == 2
    assert len(filings) == 3


def test_request_raises_after_max_retries(monkeypatch):
    api = _make_api(monkeypatch)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    api.session.get = Mock(return_value=_mock_response({}, status_code=429))

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        api.get_institutional_filings("1067983")


def test_request_raises_on_invalid_json(monkeypatch):
    api = _make_api(monkeypatch)
    response = _mock_response({}, status_code=200)
    response.json.side_effect = ValueError("no json")
    api.session.get = Mock(return_value=response)

    with pytest.raises(RuntimeError, match="Invalid JSON"):
        api.get_institutional_filings("1067983")


def test_request_propagates_http_error(monkeypatch):
    api = _make_api(monkeypatch)
    response = _mock_response({}, status_code=404)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
    api.session.get = Mock(return_value=response)

    with pytest.raises(requests.exceptions.HTTPError):
        api.get_institutional_filings("1067983")
