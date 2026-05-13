"""Unit tests for deepear agent layer with lightweight stubs."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


def _install_agno_stubs() -> None:
    """Install minimal agno stubs so deepear modules can be imported in tests."""
    agno_pkg = types.ModuleType("agno")
    agno_agent = types.ModuleType("agno.agent")
    agno_models = types.ModuleType("agno.models")
    agno_models_base = types.ModuleType("agno.models.base")

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self, prompt: str):
            return types.SimpleNamespace(content=prompt)

    class FakeModel:
        id = "fake-model"

    agno_agent.Agent = FakeAgent
    agno_models_base.Model = FakeModel
    agno_pkg.agent = agno_agent
    agno_pkg.models = agno_models
    agno_models.base = agno_models_base

    sys.modules["agno"] = agno_pkg
    sys.modules["agno.agent"] = agno_agent
    sys.modules["agno.models"] = agno_models
    sys.modules["agno.models.base"] = agno_models_base


def _install_trend_agent_dependency_stubs() -> None:
    """Install small stubs for trend_agent import dependencies."""
    toolkit_mod = types.ModuleType("deepear.src.tools.toolkits")

    class _BaseToolkit:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class NewsToolkit(_BaseToolkit):
        pass

    class StockToolkit(_BaseToolkit):
        pass

    class SentimentToolkit(_BaseToolkit):
        pass

    class SearchToolkit(_BaseToolkit):
        pass

    class PolymarketToolkit(_BaseToolkit):
        pass

    toolkit_mod.NewsToolkit = NewsToolkit
    toolkit_mod.StockToolkit = StockToolkit
    toolkit_mod.SentimentToolkit = SentimentToolkit
    toolkit_mod.SearchToolkit = SearchToolkit
    toolkit_mod.PolymarketToolkit = PolymarketToolkit
    sys.modules["deepear.src.tools.toolkits"] = toolkit_mod

    prompts_mod = types.ModuleType("deepear.src.prompts.trend_agent")
    prompts_mod.get_trend_scanner_instructions = lambda: "scan"
    prompts_mod.get_trend_evaluator_instructions = lambda: "eval"
    prompts_mod.get_trend_scan_task = lambda text: f"scan:{text}"
    prompts_mod.format_scan_context = lambda *_args, **_kwargs: "ctx"
    prompts_mod.get_trend_eval_task = lambda task, raw: f"eval:{task}:{raw}"
    sys.modules["deepear.src.prompts.trend_agent"] = prompts_mod

    schema_mod = types.ModuleType("deepear.src.schema.models")
    schema_mod.ScanContext = type("ScanContext", (), {})
    sys.modules["deepear.src.schema.models"] = schema_mod


def _load_trend_agent_module():
    _install_agno_stubs()
    _install_trend_agent_dependency_stubs()
    # Avoid executing deepear.src.agents.__init__ (imports many heavy modules).
    agents_pkg = types.ModuleType("deepear.src.agents")
    agents_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "deepear" / "src" / "agents")]
    sys.modules["deepear.src.agents"] = agents_pkg
    sys.modules.pop("deepear.src.agents.trend_agent", None)
    return importlib.import_module("deepear.src.agents.trend_agent")


def test_trend_agent_skip_polymarket_removes_poly_tool():
    trend_agent_mod = _load_trend_agent_module()

    model = types.SimpleNamespace(id="reasoning-model")
    agent = trend_agent_mod.TrendAgent(
        db=object(),
        model=model,
        tool_model=model,
        sentiment_mode="bert",
        skip_polymarket=True,
    )

    scanner_tools = agent.scanner.kwargs["tools"]
    assert len(scanner_tools) == 4
    assert agent.polymarket_toolkit is None


def test_trend_agent_includes_polymarket_when_enabled():
    trend_agent_mod = _load_trend_agent_module()

    model = types.SimpleNamespace(id="reasoning-model")
    agent = trend_agent_mod.TrendAgent(
        db=object(),
        model=model,
        tool_model=model,
        sentiment_mode="bert",
        skip_polymarket=False,
    )

    scanner_tools = agent.scanner.kwargs["tools"]
    assert len(scanner_tools) == 5
    assert agent.polymarket_toolkit is not None
