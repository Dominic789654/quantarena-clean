"""Unit tests for robust fallback behavior in deepfund.src.llm.inference."""

from __future__ import annotations

from pydantic import BaseModel, Field

from deepfund.src.llm import inference


class RequiredDecision(BaseModel):
    action: str = Field(description="BUY, SELL, or HOLD")
    shares: int = Field(description="Number of shares", ge=0)
    reasoning: str = Field(description="Decision rationale")


class DefaultSignal(BaseModel):
    signal: str = Field(default="NEUTRAL")
    confidence: float = Field(default=50.0)


class _AlwaysFailStructured:
    def invoke(self, prompt: str):
        raise ConnectionError("Connection error")


class _AlwaysFailLLM:
    def with_structured_output(self, model, method=None):
        return _AlwaysFailStructured()

    def invoke(self, prompt: str):
        raise ConnectionError("Connection error")


class _RawResponse:
    def __init__(self, content: str):
        self.content = content


class _RawFallbackLLM(_AlwaysFailLLM):
    def invoke(self, prompt: str):
        return _RawResponse("raw fallback text")


class _JsonFallbackLLM(_AlwaysFailLLM):
    def __init__(self, content: str):
        self._content = content

    def invoke(self, prompt: str):
        return _RawResponse(self._content)

class _RecordingStructured:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return self.response


class _RecordingLLM:
    def __init__(self, response):
        self.structured = _RecordingStructured(response)
        self.methods = []

    def with_structured_output(self, model, method=None):
        self.methods.append(method)
        return self.structured

    def invoke(self, prompt: str):
        return _RawResponse('{"action": "HOLD", "shares": 0, "reasoning": "usage probe"}')


class _RecordingRawLLM(_AlwaysFailLLM):
    def __init__(self, content: str):
        self.prompts = []
        self.methods = []
        self._content = content

    def with_structured_output(self, model, method=None):
        self.methods.append(method)
        return _AlwaysFailStructured()

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return _RawResponse(self._content)



def test_agent_call_returns_required_model_and_records_tokens_on_total_failure(monkeypatch):
    monkeypatch.setattr(inference, "get_model", lambda cfg: _AlwaysFailLLM())

    inference.reset_token_tracker()
    result = inference.agent_call(
        prompt="decide trade",
        llm_config={"provider": "ark", "model": "doubao-seed-2.0-code", "max_retries": 2},
        pydantic_model=RequiredDecision,
        agent_name="required_total_fail",
    )

    assert isinstance(result, RequiredDecision)
    assert result.action.upper() in {"HOLD", "BUY", "SELL"}
    assert result.shares >= 0
    assert len(result.reasoning) > 0

    stats = inference.get_token_stats()
    assert stats["calls"] == 1
    assert stats["total_input"] > 0
    assert stats["total_output"] > 0
    assert stats["by_agent"]["required_total_fail"]["calls"] == 1


def test_agent_call_handles_get_model_failure_gracefully(monkeypatch):
    def _raise_get_model(_cfg):
        raise ValueError("bad model")

    monkeypatch.setattr(inference, "get_model", _raise_get_model)

    inference.reset_token_tracker()
    result = inference.agent_call(
        prompt="analyze",
        llm_config={"provider": "ark", "model": "invalid-model", "max_retries": 1},
        pydantic_model=DefaultSignal,
        agent_name="init_fail",
    )

    assert isinstance(result, DefaultSignal)
    assert result.signal == "NEUTRAL"

    stats = inference.get_token_stats()
    assert stats["calls"] == 1
    assert stats["by_agent"]["init_fail"]["calls"] == 1


def test_agent_call_raw_fallback_path_uses_safe_model(monkeypatch):
    monkeypatch.setattr(inference, "get_model", lambda cfg: _RawFallbackLLM())

    inference.reset_token_tracker()
    result = inference.agent_call(
        prompt="portfolio decision",
        llm_config={"provider": "ark", "model": "doubao-seed-2.0-code", "max_retries": 1},
        pydantic_model=RequiredDecision,
        agent_name="raw_fallback",
    )

    assert isinstance(result, RequiredDecision)
    assert result.shares >= 0

    stats = inference.get_token_stats()
    assert stats["calls"] == 1
    assert stats["by_agent"]["raw_fallback"]["calls"] == 1


def test_agent_call_validates_plain_json_from_raw_fallback(monkeypatch):
    monkeypatch.setattr(
        inference,
        "get_model",
        lambda cfg: _JsonFallbackLLM('{"action": "BUY", "shares": 12, "reasoning": "Momentum improving"}'),
    )

    inference.reset_token_tracker()
    result = inference.agent_call(
        prompt="portfolio decision",
        llm_config={"provider": "ark", "model": "unsupported-chat-model", "max_retries": 1},
        pydantic_model=RequiredDecision,
        agent_name="json_fallback_plain",
    )

    assert isinstance(result, RequiredDecision)
    assert result.action == "BUY"
    assert result.shares == 12
    assert result.reasoning == "Momentum improving"


def test_agent_call_validates_markdown_wrapped_json_from_raw_fallback(monkeypatch):
    monkeypatch.setattr(
        inference,
        "get_model",
        lambda cfg: _JsonFallbackLLM(
            """Here is the result:

```json
{
  "action": "SELL",
  "shares": 3,
  "reasoning": "Risk limits were breached",
}
```
"""
        ),
    )

    inference.reset_token_tracker()
    result = inference.agent_call(
        prompt="portfolio decision",
        llm_config={"provider": "ark", "model": "unsupported-chat-model", "max_retries": 1},
        pydantic_model=RequiredDecision,
        agent_name="json_fallback_markdown",
    )

    assert isinstance(result, RequiredDecision)
    assert result.action == "SELL"
    assert result.shares == 3
    assert result.reasoning == "Risk limits were breached"


def test_deepseek_uses_json_mode_prompt_contract(monkeypatch):
    llm = _RecordingLLM(RequiredDecision(action="BUY", shares=4, reasoning="valid json"))
    monkeypatch.setattr(inference, "get_model", lambda cfg: llm)

    inference.reset_token_tracker()
    result = inference.agent_call(
        prompt="portfolio decision without magic keyword",
        llm_config={"provider": "DeepSeek", "model": "deepseek-v4-flash", "max_retries": 1},
        pydantic_model=RequiredDecision,
        agent_name="deepseek_json_contract",
    )

    assert result.action == "BUY"
    assert result.shares == 4
    assert llm.methods == ["json_mode"]
    structured_prompt = llm.structured.prompts[0]
    assert "Return only valid JSON" in structured_prompt
    assert "EXAMPLE JSON OUTPUT" in structured_prompt
    assert '"action"' in structured_prompt
    assert "portfolio decision without magic keyword" in structured_prompt


def test_deepseek_raw_fallback_uses_json_prompt_contract(monkeypatch):
    llm = _RecordingRawLLM('{"action": "SELL", "shares": 2, "reasoning": "risk"}')
    monkeypatch.setattr(inference, "get_model", lambda cfg: llm)

    inference.reset_token_tracker()
    result = inference.agent_call(
        prompt="portfolio decision",
        llm_config={"provider": "deepseek", "model": "deepseek-v4-flash", "max_retries": 1},
        pydantic_model=RequiredDecision,
        agent_name="deepseek_json_raw_fallback",
    )

    assert result.action == "SELL"
    assert result.shares == 2
    assert llm.methods == ["json_mode"]
    assert "Return only valid JSON" in llm.prompts[0]
    assert "EXAMPLE JSON OUTPUT" in llm.prompts[0]
