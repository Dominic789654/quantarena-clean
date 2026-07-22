"""Unit tests for deepear search tools cache behavior."""

from __future__ import annotations

import importlib
import json
import sys
import types

import pytest

# Every module this file stubs into sys.modules. The autouse fixture below
# restores them so later test files import the real modules, not our stubs.
_STUBBED_MODULE_PREFIXES = (
    "agno",
    "deepear.src.utils.hybrid_search",
    "deepear.src.utils.search_tools",
)


def _matches_stubbed_prefix(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in _STUBBED_MODULE_PREFIXES
    )


@pytest.fixture(autouse=True)
def _restore_stubbed_modules():
    """Snapshot and restore sys.modules entries this file replaces with stubs."""
    saved = {
        name: module
        for name, module in sys.modules.items()
        if _matches_stubbed_prefix(name)
    }
    yield
    for name in [n for n in sys.modules if _matches_stubbed_prefix(n)]:
        if name in saved:
            sys.modules[name] = saved.pop(name)
        else:
            del sys.modules[name]
    sys.modules.update(saved)


def _install_search_tools_dependency_stubs() -> None:
    """Install stubs required to import deepear search tools in test env."""
    agno_pkg = types.ModuleType("agno")
    agno_tools = types.ModuleType("agno.tools")
    agno_tools_ddg = types.ModuleType("agno.tools.duckduckgo")
    agno_tools_baidu = types.ModuleType("agno.tools.baidusearch")
    agno_agent = types.ModuleType("agno.agent")

    class _DDG:
        def duckduckgo_search(self, query: str, max_results: int = 5):
            return [{"title": query, "href": "https://example.com", "body": "cached"}][:max_results]

    class _Baidu:
        def baidu_search(self, query: str, max_results: int = 5):
            return [{"title": query, "href": "https://example.cn", "body": "cached"}][:max_results]

    class _Agent:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    agno_tools_ddg.DuckDuckGoTools = _DDG
    agno_tools_baidu.BaiduSearchTools = _Baidu
    agno_agent.Agent = _Agent

    agno_pkg.tools = agno_tools
    agno_pkg.agent = agno_agent
    sys.modules["agno"] = agno_pkg
    sys.modules["agno.tools"] = agno_tools
    sys.modules["agno.tools.duckduckgo"] = agno_tools_ddg
    sys.modules["agno.tools.baidusearch"] = agno_tools_baidu
    sys.modules["agno.agent"] = agno_agent

    hybrid_mod = types.ModuleType("deepear.src.utils.hybrid_search")

    class _LocalNewsSearch:
        def __init__(self, _db):
            self.db = _db

        def search(self, _query: str, top_n: int = 5):
            return [{"title": "local", "url": "local://1", "content": "local"}][:top_n]

    hybrid_mod.LocalNewsSearch = _LocalNewsSearch
    sys.modules["deepear.src.utils.hybrid_search"] = hybrid_mod


class _FakeDB:
    def __init__(self):
        self.cache = {}
        self.saved = []

    def get_search_cache(self, query_hash: str, ttl_seconds=None):
        _ = ttl_seconds
        return self.cache.get(query_hash)

    def save_search_cache(self, query_hash: str, query: str, engine: str, results):
        if not isinstance(results, str):
            results = json.dumps(results, ensure_ascii=False)
        payload = {
            "query_hash": query_hash,
            "query": query,
            "engine": engine,
            "results": results,
        }
        self.saved.append(payload)
        self.cache[query_hash] = payload


def _load_search_tools_module():
    _install_search_tools_dependency_stubs()
    sys.modules.pop("deepear.src.utils.search_tools", None)
    return importlib.import_module("deepear.src.utils.search_tools")


def test_search_returns_cached_result_without_hitting_engine():
    mod = _load_search_tools_module()
    db = _FakeDB()
    tools = mod.SearchTools(db)

    query_hash = tools._generate_hash("tesla earnings", "ddg", 3)
    db.cache[query_hash] = {
        "query_hash": query_hash,
        "query": "tesla earnings",
        "engine": "ddg",
        "results": "cached-result",
    }

    # If engine is called, this raises and the test fails.
    tools._engines["ddg"].duckduckgo_search = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("engine should not run"))

    result = tools.search("tesla earnings", engine="ddg", max_results=3)
    assert result == "cached-result"


def test_search_saves_cache_after_live_query():
    mod = _load_search_tools_module()
    db = _FakeDB()
    tools = mod.SearchTools(db)

    tools._engines["ddg"].duckduckgo_search = lambda *_args, **_kwargs: [
        {"title": "A", "href": "https://a", "body": "alpha"}
    ]

    result = tools.search("nvda ai", engine="ddg", max_results=2, ttl=0)
    assert "https://a" in result
    assert db.saved, "Expected search results to be cached"
    assert db.saved[0]["engine"] == "ddg"


def test_search_rejects_unsupported_engine():
    mod = _load_search_tools_module()
    db = _FakeDB()
    tools = mod.SearchTools(db)

    result = tools.search("query", engine="unknown")
    assert "Unsupported engine" in result

