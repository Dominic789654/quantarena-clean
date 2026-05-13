"""Unit tests for deepear SignalFluxWorkflow filtering logic."""

from __future__ import annotations

import importlib
import json
import sys
import types


def _install_main_flow_dependency_stubs(monkeypatch) -> None:
    """Install minimal dependency stubs so main_flow can be imported."""
    agno_pkg = types.ModuleType("agno")
    agno_agent = types.ModuleType("agno.agent")

    class _Agent:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.instructions = kwargs.get("instructions", [])

        def run(self, _prompt: str):
            return types.SimpleNamespace(content="{}")

    agno_agent.Agent = _Agent
    agno_pkg.agent = agno_agent
    monkeypatch.setitem(sys.modules, "agno", agno_pkg)
    monkeypatch.setitem(sys.modules, "agno.agent", agno_agent)

    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "dotenv", dotenv_mod)

    db_mod = types.ModuleType("deepear.src.utils.database_manager")
    db_mod.DatabaseManager = type("DatabaseManager", (), {})
    monkeypatch.setitem(sys.modules, "deepear.src.utils.database_manager", db_mod)

    llm_factory = types.ModuleType("deepear.src.utils.llm.factory")
    llm_factory.get_model = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "deepear.src.utils.llm.factory", llm_factory)

    llm_router = types.ModuleType("deepear.src.utils.llm.router")
    llm_router.router = types.SimpleNamespace(
        get_reasoning_model=lambda: types.SimpleNamespace(id="reasoning"),
        get_tool_model=lambda: types.SimpleNamespace(id="tool"),
    )
    monkeypatch.setitem(sys.modules, "deepear.src.utils.llm.router", llm_router)

    search_mod = types.ModuleType("deepear.src.utils.search_tools")
    search_mod.SearchTools = type("SearchTools", (), {})
    monkeypatch.setitem(sys.modules, "deepear.src.utils.search_tools", search_mod)

    agents_mod = types.ModuleType("deepear.src.agents")
    agents_mod.TrendAgent = type("TrendAgent", (), {})
    agents_mod.FinAgent = type("FinAgent", (), {})
    agents_mod.ReportAgent = type("ReportAgent", (), {})
    agents_mod.IntentAgent = type("IntentAgent", (), {})
    monkeypatch.setitem(sys.modules, "deepear.src.agents", agents_mod)

    stock_mod = types.ModuleType("deepear.src.utils.stock_tools")
    stock_mod.StockTools = type("StockTools", (), {})
    monkeypatch.setitem(sys.modules, "deepear.src.utils.stock_tools", stock_mod)

    prompts_mod = types.ModuleType("deepear.src.prompts.trend_agent")
    prompts_mod.get_news_filter_instructions = lambda *_args, **_kwargs: "filter-inst"
    monkeypatch.setitem(sys.modules, "deepear.src.prompts.trend_agent", prompts_mod)

    ckpt_mod = types.ModuleType("deepear.src.utils.checkpointing")
    ckpt_mod.CheckpointManager = type("CheckpointManager", (), {})
    ckpt_mod.resolve_latest_run_id = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "deepear.src.utils.checkpointing", ckpt_mod)

    logging_mod = types.ModuleType("deepear.src.utils.logging_setup")
    logging_mod.setup_file_logging = lambda *_args, **_kwargs: ""
    logging_mod.make_run_id = lambda: "run_1"
    monkeypatch.setitem(sys.modules, "deepear.src.utils.logging_setup", logging_mod)

    html_mod = types.ModuleType("deepear.src.utils.md_to_html")
    html_mod.save_report_as_html = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "deepear.src.utils.md_to_html", html_mod)

    stats_mod = types.ModuleType("deepear.src.utils.stats")
    stats_mod.get_stats = lambda: types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "deepear.src.utils.stats", stats_mod)


def _load_main_flow_module(monkeypatch):
    _install_main_flow_dependency_stubs(monkeypatch)
    monkeypatch.delitem(sys.modules, "deepear.src.main_flow", raising=False)
    return importlib.import_module("deepear.src.main_flow")


class _FilterAgent:
    def __init__(self, content: str):
        self._content = content
        self.instructions = []

    def run(self, _prompt: str):
        return types.SimpleNamespace(content=self._content)


def _build_workflow(main_flow_mod, content: str = "{}"):
    workflow = main_flow_mod.SignalFluxWorkflow.__new__(main_flow_mod.SignalFluxWorkflow)
    workflow.filter_agent = _FilterAgent(content=content)
    return workflow


def test_llm_filter_short_circuit_when_depth_covers_all_news(monkeypatch):
    mod = _load_main_flow_module(monkeypatch)
    workflow = _build_workflow(mod)
    news_list = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]

    result = workflow._llm_filter_signals(news_list, depth=3, query=None)
    assert result == news_list


def test_llm_filter_returns_selected_items_for_query(monkeypatch):
    mod = _load_main_flow_module(monkeypatch)
    workflow = _build_workflow(mod, content=json.dumps({"selected_ids": [2], "themes": ["ev"]}))
    news_list = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]

    mod.extract_json = lambda content: json.loads(content)
    result = workflow._llm_filter_signals(news_list, depth=1, query="新能源")

    assert result == [{"id": 2, "title": "B"}]
    assert workflow.filter_agent.instructions == ["filter-inst"]


def test_llm_filter_returns_empty_when_no_valid_signal(monkeypatch):
    mod = _load_main_flow_module(monkeypatch)
    workflow = _build_workflow(mod, content=json.dumps({"has_valid_signals": False, "reason": "noise"}))
    news_list = [{"id": 1, "title": "A"}]

    mod.extract_json = lambda content: json.loads(content)
    result = workflow._llm_filter_signals(news_list, depth=1, query="宏观")

    assert result == []


def test_llm_filter_falls_back_to_original_news_on_parse_failure(monkeypatch):
    mod = _load_main_flow_module(monkeypatch)
    workflow = _build_workflow(mod, content="not-json")
    news_list = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]

    mod.extract_json = lambda _content: None
    result = workflow._llm_filter_signals(news_list, depth=1, query=None)

    assert result == news_list
