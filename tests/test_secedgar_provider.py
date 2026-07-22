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
        "total": {"value": 3},
        "hits": [
            {
                # Relevance-ranked older filing: must sort AFTER the newer one.
                "_source": {
                    "ciks": ["not-a-number"],
                    "display_names": ["NVIDIA CORP  (NVDA)  (CIK 0001045810)"],
                    "file_type": "4",
                    "file_date": "2026-06-20",
                    "adsh": "0001045810-26-000100",
                }
            },
            {
                "_source": {
                    "ciks": ["0001045810"],
                    "display_names": [
                        "NVIDIA CORP  (NVDA)  (CIK 0001045810)",
                        "HUANG JEN HSUN (CIK 0001234567)",
                    ],
                    "file_type": "4",
                    "file_date": "2026-07-01",
                    "adsh": "0001045810-26-000123",
                }
            },
            {
                # Full-text noise from an unrelated issuer: must be dropped.
                "_source": {
                    "ciks": ["0000899051"],
                    "display_names": ["ALLSTATE CORP  (ALL)  (CIK 0000899051)"],
                    "file_type": "4",
                    "file_date": "2026-07-02",
                    "adsh": "0000899051-26-000042",
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
    SECEdgarAPI._last_request_ts = 0.0
    yield
    SECEdgarAPI.clear_cache()
    SECEdgarAPI._last_request_ts = 0.0


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


def test_get_institutional_filings_excludes_same_day(monkeypatch):
    """Strictly-before semantics, matching the AlphaVantage insider filter."""
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))

    filings = api.get_institutional_filings(
        "1067983", trading_date=datetime(2026, 2, 14)
    )

    assert [f.filing_date for f in filings] == ["2025-11-14"]


def test_get_institutional_filings_warns_when_window_too_short(monkeypatch):
    """A trading_date older than the recent-filings window must not fail silently."""
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))

    with pytest.warns(RuntimeWarning, match="may be incomplete"):
        filings = api.get_institutional_filings(
            "1067983", trading_date=datetime(2018, 1, 2)
        )

    assert filings == []


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


def test_get_insider_filings_parses_verifies_and_sorts(monkeypatch):
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(FORM4_SEARCH_FIXTURE))

    filings = api.get_insider_filings("nvda", trading_date=datetime(2026, 7, 10))

    assert all(isinstance(f, InsiderFiling) for f in filings)
    # The unrelated-issuer hit (ALL) is dropped by the "(NVDA)" marker check.
    assert len(filings) == 2
    # Relevance-ranked hits are re-sorted by filing date, newest first.
    assert [f.filing_date for f in filings] == ["2026-07-01", "2026-06-20"]
    assert filings[0].ticker == "NVDA"
    assert filings[0].cik == "0001045810"
    assert filings[0].filing_url is not None
    # Non-numeric CIK parses without crashing, just yields no URL.
    assert filings[1].cik == "not-a-number"
    assert filings[1].filing_url is None

    params = api.session.get.call_args.kwargs["params"]
    assert params["q"] == '"NVDA"'
    assert params["forms"] == "4"
    assert params["enddt"] == "2026-07-10"


def test_get_insider_filings_excludes_same_day_and_unparseable_dates(monkeypatch):
    """Strictly-before semantics: same-day filings are future info at the open."""
    api = _make_api(monkeypatch)
    fixture = {
        "hits": {"hits": [
            {"_source": {
                "ciks": ["0001045810"],
                "display_names": ["NVIDIA CORP  (NVDA)  (CIK 0001045810)"],
                "file_date": "2026-07-10", "adsh": "a-1",
            }},
            {"_source": {
                "ciks": ["0001045810"],
                "display_names": ["NVIDIA CORP  (NVDA)  (CIK 0001045810)"],
                "file_date": "garbage", "adsh": "a-2",
            }},
        ]}
    }
    api.session.get = Mock(return_value=_mock_response(fixture))

    filings = api.get_insider_filings("NVDA", trading_date=datetime(2026, 7, 10))

    assert filings == []


def test_get_insider_filings_respects_limit(monkeypatch):
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(FORM4_SEARCH_FIXTURE))

    filings = api.get_insider_filings("NVDA", trading_date=datetime(2026, 7, 10), limit=1)

    assert len(filings) == 1


def test_cache_expires_after_ttl(monkeypatch):
    api = _make_api(monkeypatch)
    api.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))

    base = 1_000_000.0
    monkeypatch.setattr("time.time", lambda: base)
    api.get_institutional_filings("1067983")
    # Just inside the TTL: served from cache.
    monkeypatch.setattr("time.time", lambda: base + api.SUBMISSIONS_CACHE_TTL - 1)
    api.get_institutional_filings("1067983")
    assert api.session.get.call_count == 1
    # Past the TTL: refetched.
    monkeypatch.setattr("time.time", lambda: base + api.SUBMISSIONS_CACHE_TTL + 1)
    api.get_institutional_filings("1067983")
    assert api.session.get.call_count == 2


def test_throttle_is_shared_across_instances(monkeypatch):
    """The SEC fair-access interval must hold even for freshly built clients."""
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    first = _make_api(monkeypatch)
    first.min_request_interval = 5.0
    first.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))
    first.get_institutional_filings("1067983")
    assert sleeps == []  # cold start: no wait

    second = _make_api(monkeypatch)  # fresh instance, as Router/analysts create
    second.min_request_interval = 5.0
    second.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))
    second.get_institutional_filings("1354735")

    assert len(sleeps) == 1 and 0 < sleeps[0] <= 5.0


def test_request_retries_on_throttle(monkeypatch):
    api = _make_api(monkeypatch)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    throttled = _mock_response({}, status_code=429)
    ok = _mock_response(SUBMISSIONS_FIXTURE)
    api.session.get = Mock(side_effect=[throttled, ok])

    filings = api.get_institutional_filings("1067983")

    assert api.session.get.call_count == 2
    assert len(filings) == 3


def test_no_backoff_sleep_after_final_attempt(monkeypatch):
    api = _make_api(monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    api.session.get = Mock(return_value=_mock_response({}, status_code=429))

    with pytest.raises(RuntimeError):
        api.get_institutional_filings("1067983")

    # 3 attempts -> only 2 backoff sleeps (none after the last failure).
    assert sleeps == [1, 2]


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
