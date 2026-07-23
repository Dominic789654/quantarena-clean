"""Unit tests for the alt-data snapshot store and provider replay wiring."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import Mock

import pytest

from deepfund.src.apis.alt_snapshot import SnapshotStore
from deepfund.src.apis.apewisdom.api import ApeWisdomAPI
from deepfund.src.apis.secedgar.api import SECEdgarAPI


# ----------------------------------------------------------------------
# SnapshotStore
# ----------------------------------------------------------------------

@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("TESTPROV_SNAPSHOT_MODE", "refresh")
    monkeypatch.setenv("TESTPROV_SNAPSHOT_DIR", str(tmp_path))
    return SnapshotStore("TESTPROV", str(tmp_path))


def test_store_save_and_load_exact_today(store):
    payload = {"results": [1, 2, 3]}
    path = store.save("wsb/page_1", payload)

    assert path is not None and path.exists()
    assert store.load_exact("wsb/page_1") == payload
    assert store.load_exact("wsb/page_1", date.today() - timedelta(days=1)) is None


def test_store_load_nearest_walks_back(store, tmp_path):
    payload = {"results": ["captured earlier"]}
    store.save("wsb/page_1", payload)
    today_file = store._path_for("wsb/page_1", date.today())
    # Re-date the snapshot 3 days into the past.
    older = store._path_for("wsb/page_1", date.today() - timedelta(days=3))
    older.parent.mkdir(parents=True, exist_ok=True)
    today_file.rename(older)

    assert store.load_exact("wsb/page_1") is None
    assert store.load_nearest("wsb/page_1") == payload
    # Outside the lookback window: not found.
    assert store.load_nearest("wsb/page_1", date.today() - timedelta(days=30)) is None


def test_store_mode_defaults_and_validation(monkeypatch, tmp_path):
    monkeypatch.delenv("TESTPROV_SNAPSHOT_MODE", raising=False)
    store = SnapshotStore("TESTPROV", str(tmp_path))
    assert store.mode == "off" and not store.enabled

    monkeypatch.setenv("TESTPROV_SNAPSHOT_MODE", "bogus")
    assert store.mode == "off"
    monkeypatch.setenv("TESTPROV_SNAPSHOT_MODE", "local_only")
    assert store.mode == "local_only" and store.enabled


def test_store_corrupt_snapshot_returns_none(store):
    path = store.save("wsb/page_1", {"ok": 1})
    path.write_text("{not json", encoding="utf-8")

    assert store.load_exact("wsb/page_1") is None


def test_store_key_sanitization(store):
    path = store.save("a/../weird key!/x", {"ok": 1})

    assert path is not None
    assert ".." not in path.parts
    assert store.snapshot_dir in path.parents


# ----------------------------------------------------------------------
# ApeWisdom snapshot wiring
# ----------------------------------------------------------------------

PAGE_FIXTURE = {
    "count": 1, "pages": 1, "current_page": 1,
    "results": [{"rank": 1, "ticker": "MU", "name": "Micron",
                 "mentions": 474, "upvotes": 2441,
                 "rank_24h_ago": 2, "mentions_24h_ago": 237}],
}


def _mock_response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status = Mock()
    return response


@pytest.fixture(autouse=True)
def clear_provider_state():
    ApeWisdomAPI.clear_cache()
    ApeWisdomAPI._last_request_ts = 0.0
    SECEdgarAPI.clear_cache()
    SECEdgarAPI._last_request_ts = 0.0
    yield
    ApeWisdomAPI.clear_cache()
    SECEdgarAPI.clear_cache()


@pytest.fixture
def ape(monkeypatch, tmp_path):
    monkeypatch.setenv("APEWISDOM_SNAPSHOT_DIR", str(tmp_path))
    api = ApeWisdomAPI()
    api.min_request_interval = 0.0
    api.session.get = Mock(return_value=_mock_response(PAGE_FIXTURE))
    return api


def test_apewisdom_refresh_saves_daily_snapshot(monkeypatch, ape, tmp_path):
    monkeypatch.setenv("APEWISDOM_SNAPSHOT_MODE", "refresh")

    ape.get_trending()

    saved = list(tmp_path.rglob("*.json"))
    assert len(saved) == 1
    assert saved[0].name == f"{date.today().isoformat()}.json"
    assert ape.session.get.call_count == 1


def test_apewisdom_local_only_replays_without_network(monkeypatch, ape):
    monkeypatch.setenv("APEWISDOM_SNAPSHOT_MODE", "refresh")
    ape.get_trending()  # capture
    ApeWisdomAPI.clear_cache()

    monkeypatch.setenv("APEWISDOM_SNAPSHOT_MODE", "local_only")
    mentions = ape.get_trending(as_of=datetime.now())

    assert mentions[0].ticker == "MU"
    assert ape.session.get.call_count == 1  # no second network call


def test_apewisdom_local_only_missing_snapshot_raises(monkeypatch, ape):
    monkeypatch.setenv("APEWISDOM_SNAPSHOT_MODE", "local_only")

    with pytest.raises(FileNotFoundError, match="snapshot not found"):
        ape.get_trending(as_of=datetime(2020, 1, 6))
    ape.session.get.assert_not_called()


def test_apewisdom_refresh_backfills_snapshot_on_warm_ttl_cache(monkeypatch, ape, tmp_path):
    """A warm in-memory TTL cache must not skip daily capture: if today's
    snapshot file is missing (e.g. day rolled over), the cache hit backfills it."""
    monkeypatch.setenv("APEWISDOM_SNAPSHOT_MODE", "refresh")

    ape.get_trending()  # fetch + save; memory cache now warm
    snapshot = next(tmp_path.rglob("*.json"))
    snapshot.unlink()  # simulate the day boundary: no snapshot for "today"

    ape.get_trending()  # served from TTL cache — must still write the snapshot

    assert ape.session.get.call_count == 1
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_apewisdom_prefer_local_serves_same_day_and_saves(monkeypatch, ape, tmp_path):
    monkeypatch.setenv("APEWISDOM_SNAPSHOT_MODE", "prefer_local")

    ape.get_trending()  # miss -> live fetch -> save today's snapshot
    assert ape.session.get.call_count == 1
    assert len(list(tmp_path.rglob("*.json"))) == 1

    ApeWisdomAPI.clear_cache()  # drop memory cache; snapshot must serve
    mentions = ape.get_trending()
    assert mentions[0].ticker == "MU"
    assert ape.session.get.call_count == 1  # same-day snapshot hit, no refetch


def test_apewisdom_prefer_local_misses_other_day_and_fetches_live(monkeypatch, ape):
    """prefer_local is exact-day: a historical as_of without a snapshot
    falls through to a live fetch (with the analyst-level warning)."""
    monkeypatch.setenv("APEWISDOM_SNAPSHOT_MODE", "prefer_local")

    ape.get_trending(as_of=datetime(2020, 1, 6))

    assert ape.session.get.call_count == 1


def test_apewisdom_off_mode_never_touches_disk(monkeypatch, ape, tmp_path):
    monkeypatch.delenv("APEWISDOM_SNAPSHOT_MODE", raising=False)

    ape.get_trending()

    assert list(tmp_path.rglob("*.json")) == []


# ----------------------------------------------------------------------
# SEC EDGAR snapshot wiring
# ----------------------------------------------------------------------

SUBMISSIONS_FIXTURE = {
    "cik": "0001067983",
    "filings": {"recent": {
        "form": ["13F-HR"], "filingDate": ["2026-05-15"],
        "accessionNo": ["0000950123-26-005555"], "primaryDocument": ["a.xml"],
    }},
}


FORM4_FIXTURE = {
    "hits": {"hits": [{
        "_source": {
            "ciks": ["0001045810"],
            "display_names": ["NVIDIA CORP  (NVDA)  (CIK 0001045810)"],
            "file_type": "4",
            "file_date": "2026-07-01",
            "adsh": "0001045810-26-000123",
        }
    }]}
}


def test_secedgar_form4_local_only_replays_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "QuantArenaTest/1.0 (test@example.com)")
    monkeypatch.setenv("SEC_EDGAR_SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setenv("SEC_EDGAR_SNAPSHOT_MODE", "refresh")

    api = SECEdgarAPI()
    api.min_request_interval = 0.0
    api.session.get = Mock(return_value=_mock_response(FORM4_FIXTURE))
    trading_date = datetime.now()
    api.get_insider_filings("NVDA", trading_date=trading_date)  # capture
    SECEdgarAPI.clear_cache()

    monkeypatch.setenv("SEC_EDGAR_SNAPSHOT_MODE", "local_only")
    filings = api.get_insider_filings("NVDA", trading_date=trading_date)

    assert filings[0].filing_date == "2026-07-01"
    assert api.session.get.call_count == 1  # replay served from disk


def test_secedgar_local_only_replays_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "QuantArenaTest/1.0 (test@example.com)")
    monkeypatch.setenv("SEC_EDGAR_SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setenv("SEC_EDGAR_SNAPSHOT_MODE", "refresh")

    api = SECEdgarAPI()
    api.min_request_interval = 0.0
    api.session.get = Mock(return_value=_mock_response(SUBMISSIONS_FIXTURE))
    api.get_institutional_filings("1067983")  # capture
    SECEdgarAPI.clear_cache()

    monkeypatch.setenv("SEC_EDGAR_SNAPSHOT_MODE", "local_only")
    filings = api.get_institutional_filings("1067983", trading_date=datetime.now())

    assert filings[0].filing_date == "2026-05-15"
    assert api.session.get.call_count == 1
