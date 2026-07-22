"""Unit tests for DeepEar's SEC EDGAR insider tools and toolkit adapter."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import Mock

import pytest

from deepear.src.utils.insider_tools import InsiderTools
from deepfund.src.apis.secedgar.api_model import InsiderFiling, InstitutionalFiling


FORM4 = InsiderFiling(
    ticker="NVDA",
    cik="0001045810",
    filer_names=["HUANG JEN HSUN"],
    filing_date="2026-07-01",
    accession_no="0001045810-26-000123",
    filing_url="https://www.sec.gov/Archives/edgar/data/1045810/x-index.htm",
)

F13 = InstitutionalFiling(
    cik="0001067983",
    form="13F-HR",
    filing_date="2026-05-15",
    accession_no="0000950123-26-005555",
    filing_url="https://www.sec.gov/Archives/edgar/data/1067983/y-index.htm",
)


def _tools_with_mock_api() -> tuple[InsiderTools, Mock]:
    tools = InsiderTools()
    api = Mock()
    api.get_insider_filings.return_value = [FORM4]
    api.get_institutional_filings.return_value = [F13]
    tools._api = api
    return tools, api


def test_get_recent_insider_filings_returns_dicts():
    tools, api = _tools_with_mock_api()

    filings = tools.get_recent_insider_filings("NVDA", days_back=30, limit=10)

    api.get_insider_filings.assert_called_once_with("NVDA", days_back=30, limit=10)
    assert filings == [FORM4.model_dump()]


def test_get_institution_13f_returns_dicts():
    tools, api = _tools_with_mock_api()

    filings = tools.get_institution_13f("berkshire_hathaway", limit=5)

    api.get_institutional_filings.assert_called_once_with("berkshire_hathaway", limit=5)
    assert filings == [F13.model_dump()]


def test_init_failure_is_lazy_and_retried(monkeypatch):
    """Missing SEC_EDGAR_USER_AGENT must not break toolkit construction, and a
    later env fix must take effect without recreating the tools object."""
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    tools = InsiderTools()  # must not raise

    with pytest.raises(RuntimeError, match="SEC EDGAR unavailable"):
        tools.get_recent_insider_filings("NVDA")

    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "QuantArenaTest/1.0 (test@example.com)")
    api = tools._get_api()  # construction retried, now succeeds
    assert api is not None


def _pop_module_stubs() -> dict:
    """Remove hand-made module stubs (installed by other test files, e.g.
    test_deepear_agents.py) that would shadow the real toolkits/agno modules.
    Real modules have __file__; ad-hoc ModuleType stubs do not."""
    saved = {}
    for name in list(sys.modules):
        if name == "deepear.src.tools.toolkits" or name == "agno" or name.startswith("agno."):
            if getattr(sys.modules[name], "__file__", None) is None:
                saved[name] = sys.modules.pop(name)
    return saved


class TestInsiderToolkit:
    """Toolkit adapter tests (agno Toolkit wrapping InsiderTools)."""

    @pytest.fixture
    def insider_toolkit_cls(self):
        saved_stubs = _pop_module_stubs()
        try:
            pytest.importorskip("agno.tools")
            toolkits_mod = importlib.import_module("deepear.src.tools.toolkits")
            yield toolkits_mod.InsiderToolkit
        finally:
            sys.modules.update(saved_stubs)

    @pytest.fixture
    def toolkit(self, insider_toolkit_cls):
        toolkit = insider_toolkit_cls()
        api = Mock()
        api.get_insider_filings.return_value = [FORM4]
        api.get_institutional_filings.return_value = [F13]
        toolkit._insider_tools._api = api
        return toolkit

    def test_get_insider_filings_formats_text(self, toolkit):
        text = toolkit.get_insider_filings("NVDA", days_back=30, count=10)

        assert "NVDA Form 4" in text
        assert "2026-07-01" in text
        assert "HUANG JEN HSUN" in text
        assert FORM4.filing_url in text

    def test_get_institution_13f_formats_text(self, toolkit):
        text = toolkit.get_institution_13f("berkshire_hathaway", count=5)

        assert "13F-HR" in text
        assert "2026-05-15" in text
        assert F13.filing_url in text

    def test_empty_results_return_friendly_message(self, toolkit):
        toolkit._insider_tools._api.get_insider_filings.return_value = []

        text = toolkit.get_insider_filings("ZZZZ")

        assert "无 Form 4" in text

    def test_unavailable_api_returns_error_string(self, insider_toolkit_cls, monkeypatch):
        monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
        toolkit = insider_toolkit_cls()

        text = toolkit.get_insider_filings("NVDA")

        assert "失败" in text
        assert "SEC EDGAR unavailable" in text

    def test_http_error_degrades_to_error_string(self, toolkit):
        """Any upstream exception (e.g. SEC 403 ban page) must stay inside the tool."""
        import requests

        toolkit._insider_tools._api.get_insider_filings.side_effect = (
            requests.exceptions.HTTPError("403 Client Error")
        )
        toolkit._insider_tools._api.get_institutional_filings.side_effect = (
            requests.exceptions.HTTPError("403 Client Error")
        )

        assert "失败" in toolkit.get_insider_filings("NVDA")
        assert "失败" in toolkit.get_institution_13f("blackrock")
