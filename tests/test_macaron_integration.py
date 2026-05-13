"""Focused tests for Macaron Responses API integration paths."""

from __future__ import annotations

import importlib
import math
import sys
import types

from pydantic import BaseModel, Field

from backtest.engine import BacktestEngine
from backtest.workflow_adapter import BacktestWorkflowAdapter
from deepfund.src.llm import inference
from shared.utils import macaron_responses
from shared.utils.path_manager import setup_paths

setup_paths()


class _DecisionModel(BaseModel):
    action: str = Field(description="BUY, SELL, or HOLD")
    shares: int = Field(description="Number of shares")
    reasoning: str = Field(description="Decision rationale")


def test_build_pydantic_schema_marks_all_object_fields_required():
    from deepfund.src.graph.schema import AnalystSignal, Decision, PositionRisk

    for model_cls in (AnalystSignal, Decision, PositionRisk):
        schema = macaron_responses.build_pydantic_schema(model_cls)
        assert schema["required"] == list(schema["properties"].keys())


def test_build_ticker_weight_schema_marks_all_tickers_required():
    schema = macaron_responses.build_ticker_weight_schema(["AAA", "BBB"])

    assert schema["required"] == ["AAA", "BBB"]
    assert set(schema["properties"]) == {"AAA", "BBB"}


def _install_agno_stubs() -> None:
    """Install minimal agno stubs so portfolio_allocator imports cleanly."""
    agno_pkg = types.ModuleType("agno")
    agno_agent = types.ModuleType("agno.agent")
    agno_models = types.ModuleType("agno.models")

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def run(self, prompt: str):
            return types.SimpleNamespace(content=prompt)

    class _FakeModel:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    agno_agent.Agent = _FakeAgent
    agno_pkg.agent = agno_agent
    agno_pkg.models = agno_models

    sys.modules.setdefault("agno", agno_pkg)
    sys.modules.setdefault("agno.agent", agno_agent)
    sys.modules.setdefault("agno.models", agno_models)

    for name in [
        "agno.models.openai",
        "agno.models.ollama",
        "agno.models.dashscope",
        "agno.models.deepseek",
        "agno.models.openrouter",
    ]:
        module = types.ModuleType(name)
        module_name = name.rsplit(".", 1)[-1]
        class_name = {
            "openai": "OpenAIChat",
            "ollama": "Ollama",
            "dashscope": "DashScope",
            "deepseek": "DeepSeek",
            "openrouter": "OpenRouter",
        }[module_name]
        setattr(module, class_name, _FakeModel)
        sys.modules.setdefault(name, module)


def test_call_macaron_json_builds_strict_schema_request(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "output": [
                    {
                        "content": [
                            {"text": '{"ok": true, "answer": "pong"}'}
                        ]
                    }
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7},
            }

    def _fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(macaron_responses.requests, "post", _fake_post)

    parsed, raw = macaron_responses.call_macaron_json(
        "Return pong as JSON.",
        {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "answer": {"type": "string"},
            },
            "required": ["ok", "answer"],
        },
        schema_name="pong_response",
        model="gpt-5.4",
        url="https://example.test/responses",
        api_key="secret",
        timeout=45,
    )

    assert parsed == {"ok": True, "answer": "pong"}
    assert raw["usage"]["input_tokens"] == 11
    assert captured["url"] == "https://example.test/responses"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["json"]["input"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Return pong as JSON.",
                }
            ],
        }
    ]
    assert captured["json"]["text"]["format"]["type"] == "json_schema"
    assert captured["json"]["text"]["format"]["strict"] is True
    assert captured["timeout"] == 45


def test_normalize_response_payload_handles_transcript_wrapper():
    transcript = (
        'event: response.output_text.done\n'
        'data: {"type":"response.output_text.done","text":"{\\"ok\\":true}"}\n\n'
        'event: response.completed\n'
        'data: {"type":"response.completed","response":{"id":"resp_123","usage":{"input_tokens":5,"output_tokens":2},"output":[]}}\n\n'
    )

    normalized = macaron_responses.normalize_response_payload(transcript)

    assert normalized["id"] == "resp_123"
    assert normalized["usage"]["input_tokens"] == 5
    assert normalized["output_text"] == '{"ok":true}'


def test_call_macaron_json_handles_event_transcript(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return (
                'event: response.output_text.done\n'
                'data: {"type":"response.output_text.done","text":"{\\"ok\\":true}"}\n\n'
                'event: response.completed\n'
                'data: {"type":"response.completed","response":{"usage":{"input_tokens":9,"output_tokens":4},"output":[]}}\n\n'
            )

    monkeypatch.setattr(macaron_responses.requests, "post", lambda *args, **kwargs: _Response())

    parsed, raw = macaron_responses.call_macaron_json(
        "Return pong as JSON.",
        {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
    )

    assert parsed == {"ok": True}
    assert raw["usage"]["output_tokens"] == 4


def test_parse_json_text_accepts_trailing_prose():
    parsed = macaron_responses.parse_json_text(
        '{"AAA": 0.2, "BBB": 0.0}\n\nKept extra cash because only one ticker is bullish.'
    )

    assert parsed == {"AAA": 0.2, "BBB": 0.0}


def test_build_schema_guided_prompt_appends_json_instruction():
    guided = macaron_responses.build_schema_guided_prompt(
        "Decide whether the ticker is bullish.",
        {
            "type": "object",
            "properties": {
                "signal": {"type": "string"},
                "justification": {"type": "string"},
            },
            "required": ["signal", "justification"],
        },
    )

    assert guided.startswith("Decide whether the ticker is bullish.")
    assert "Return ONLY a valid JSON object" in guided
    assert '"signal"' in guided


def test_collect_signals_only_preserves_summary_and_direction():
    adapter = BacktestWorkflowAdapter.__new__(BacktestWorkflowAdapter)

    adapter.collect_signals_only_parallel_v2 = lambda trading_date, prices: {
        "AAA": {
            "priority_score": 0.8,
            "summary": {
                "bullish_count": 2,
                "bearish_count": 0,
                "neutral_count": 1,
                "avg_confidence": 0.7,
            },
            "analyst_signals": [],
        },
        "BBB": {
            "priority_score": 0.3,
            "summary": {
                "bullish_count": 0,
                "bearish_count": 1,
                "neutral_count": 2,
                "avg_confidence": 0.4,
            },
            "analyst_signals": [],
        },
    }

    signals = BacktestWorkflowAdapter.collect_signals_only(
        adapter,
        trading_date="2026-04-21",
        prices={"AAA": 10.0, "BBB": 20.0},
    )

    assert signals["AAA"]["signal"] == "BULLISH"
    assert signals["AAA"]["summary"]["bullish_count"] == 2
    assert signals["AAA"]["confidence"] == 0.7
    assert signals["BBB"]["signal"] == "BEARISH"
    assert signals["BBB"]["summary"]["bearish_count"] == 1


def test_agent_call_uses_macaron_structured_path(monkeypatch):
    def _fake_call(prompt, model_cls, **kwargs):
        assert model_cls is _DecisionModel
        return (
            _DecisionModel(action="BUY", shares=12, reasoning="Schema-valid response"),
            {"usage": {"input_tokens": 23, "output_tokens": 9}},
        )

    monkeypatch.setattr(inference, "call_macaron_pydantic", _fake_call)

    inference.reset_token_tracker()
    result = inference.agent_call(
        prompt="Make a trade decision.",
        llm_config={"provider": "macaron", "model": "gpt-5.4", "max_retries": 1},
        pydantic_model=_DecisionModel,
        agent_name="macaron_structured",
    )

    assert isinstance(result, _DecisionModel)
    assert result.action == "BUY"
    assert result.shares == 12

    stats = inference.get_token_stats()
    assert stats["calls"] == 1
    assert stats["total_input"] == 23
    assert stats["total_output"] == 9
    assert stats["by_agent"]["macaron_structured"]["calls"] == 1


def test_portfolio_allocator_uses_macaron_branch(monkeypatch):
    _install_agno_stubs()
    portfolio_allocator = importlib.import_module("backtest.portfolio_allocator")

    monkeypatch.setenv("REASONING_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("REASONING_MODEL_ID", "gpt-4o")

    recorded = {}

    def _fake_macaron(prompt, schema, **kwargs):
        assert "AAA" in schema["properties"]
        assert "BBB" in schema["properties"]
        return ({"AAA": 0.8, "BBB": 0.4}, {"usage": {"input_tokens": 10, "output_tokens": 5}})

    def _fake_record(agent_name, input_tokens, output_tokens, provider):
        recorded["agent_name"] = agent_name
        recorded["input_tokens"] = input_tokens
        recorded["output_tokens"] = output_tokens
        recorded["provider"] = provider

    monkeypatch.setattr(portfolio_allocator, "call_macaron_json", _fake_macaron)
    monkeypatch.setattr(portfolio_allocator, "record_token_usage", _fake_record)

    allocator = portfolio_allocator.PortfolioAllocator(
        personality="balanced",
        llm_provider="macaron",
        llm_model="gpt-5.4",
    )
    allocations = allocator.allocate(
        signals={
            "AAA": {"signal": "BULLISH", "justification": "Strong momentum", "confidence": 0.9},
            "BBB": {"signal": "NEUTRAL", "justification": "Mixed setup", "confidence": 0.5},
        },
        current_portfolio=portfolio_allocator.Portfolio(cashflow=100000.0, positions={"AAA": 0, "BBB": 0}),
        prices={"AAA": 100.0, "BBB": 50.0},
        trading_date="2026-04-19",
    )

    assert math.isclose(sum(allocations.values()), 1.0, rel_tol=1e-9)
    assert math.isclose(allocations["AAA"], 2 / 3, rel_tol=1e-9)
    assert math.isclose(allocations["BBB"], 1 / 3, rel_tol=1e-9)
    assert recorded == {
        "agent_name": "portfolio_allocator",
        "input_tokens": 10,
        "output_tokens": 5,
        "provider": "macaron",
    }


def test_portfolio_allocator_rejects_partial_macaron_payload(monkeypatch):
    _install_agno_stubs()
    portfolio_allocator = importlib.import_module("backtest.portfolio_allocator")

    monkeypatch.setenv("REASONING_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("REASONING_MODEL_ID", "gpt-4o")

    def _fake_macaron(prompt, schema, **kwargs):
        return ({"AAA": 0.8}, {"usage": {"input_tokens": 10, "output_tokens": 5}})

    monkeypatch.setattr(portfolio_allocator, "call_macaron_json", _fake_macaron)

    allocator = portfolio_allocator.PortfolioAllocator(
        personality="balanced",
        llm_provider="macaron",
        llm_model="gpt-5.4",
    )
    allocations = allocator.allocate(
        signals={
            "AAA": {"signal": "BULLISH", "justification": "Strong momentum", "confidence": 0.9},
            "BBB": {"signal": "NEUTRAL", "justification": "Mixed setup", "confidence": 0.5},
        },
        current_portfolio=portfolio_allocator.Portfolio(cashflow=0.0, positions={"AAA": 10, "BBB": 20}),
        prices={"AAA": 100.0, "BBB": 50.0},
        trading_date="2026-04-19",
    )

    assert allocations == {"AAA": 0.5, "BBB": 0.5}


def test_backtest_engine_passes_resolved_llm_config_to_allocator(monkeypatch, tmp_path):
    import backtest.engine as engine_module

    captured = {}

    class _StubAllocator:
        def __init__(self, personality="balanced", llm_provider=None, llm_model=None):
            captured["personality"] = personality
            captured["llm_provider"] = llm_provider
            captured["llm_model"] = llm_model

    class _StubWorkflowAdapter:
        def close(self):
            return None

    monkeypatch.setenv("REASONING_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("REASONING_MODEL_ID", "gpt-4o")
    monkeypatch.setattr(engine_module, "PortfolioAllocator", _StubAllocator)
    monkeypatch.setattr(engine_module, "PORTFOLIO_ALLOCATOR_AVAILABLE", True)
    monkeypatch.setattr(engine_module, "create_workflow_adapter", lambda **kwargs: _StubWorkflowAdapter())

    engine = BacktestEngine(
        tickers=["AAA"],
        start_date="2024-01-01",
        end_date="2024-01-05",
        db_path=str(tmp_path / "macaron_engine.db"),
        use_llm=True,
        personality="balanced",
        config={"llm": {"provider": "macaron", "model": "gpt-5.4"}},
    )
    try:
        assert captured["personality"] == "balanced"
        assert captured["llm_provider"] == "macaron"
        assert captured["llm_model"] == "gpt-5.4"
    finally:
        engine.close()
