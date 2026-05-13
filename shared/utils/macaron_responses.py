"""Shared helpers for the Macaron Responses API.

This module centralizes the repository's direct Responses API integration so
both runtime code and standalone scripts can reuse the same request/response
handling.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple, Type

import requests
from pydantic import BaseModel


DEFAULT_MACARON_URL = "https://cc.macaron.xin/openai/v1/responses"
DEFAULT_MACARON_MODEL = "gpt-5.4"
DEFAULT_MACARON_TIMEOUT_SECONDS = 120


def get_macaron_base_url(explicit_url: str | None = None) -> str:
    """Resolve the Responses API URL from explicit input or environment."""
    if explicit_url and explicit_url.strip():
        return explicit_url.strip()
    env_url = os.getenv("MACARON_BASE_URL")
    if env_url and env_url.strip():
        return env_url.strip()
    return DEFAULT_MACARON_URL


def get_macaron_api_key(explicit_api_key: str | None = None) -> str:
    """Resolve the Macaron API key from explicit input or environment."""
    if explicit_api_key and explicit_api_key.strip():
        return explicit_api_key.strip()
    env_key = os.getenv("MACARON_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    raise ValueError("Missing API key. Set MACARON_API_KEY or pass an explicit key.")


def _tighten_schema(node: Any) -> Any:
    """Recursively add strict object defaults for Responses API schemas."""
    if isinstance(node, dict):
        tightened = {key: _tighten_schema(value) for key, value in node.items()}
        if tightened.get("type") == "object":
            tightened.setdefault("additionalProperties", False)
            properties = tightened.get("properties")
            if isinstance(properties, dict) and properties:
                tightened.setdefault("required", list(properties.keys()))
        return tightened
    if isinstance(node, list):
        return [_tighten_schema(item) for item in node]
    return node


def build_pydantic_schema(model_cls: Type[BaseModel]) -> Dict[str, Any]:
    """Build a strict JSON schema for a Pydantic response model."""
    return _tighten_schema(model_cls.model_json_schema())


def build_ticker_weight_schema(tickers: Sequence[str]) -> Dict[str, Any]:
    """Build a strict schema for ticker -> weight mappings."""
    properties = {
        str(ticker): {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        }
        for ticker in tickers
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties.keys()),
    }


def build_macaron_payload(
    prompt: str,
    schema_name: str,
    schema: Dict[str, Any],
    model: str = DEFAULT_MACARON_MODEL,
) -> Dict[str, Any]:
    """Build a Responses API payload using strict JSON-schema output."""
    return {
        "model": model,
        # Macaron's gateway is more reliable when `input` uses the canonical
        # list-of-messages shape rather than the string shorthand.
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    }
                ],
            }
        ],
        "stream": False,
        "reasoning": {"effort": "none"},
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": _tighten_schema(schema),
            }
        },
    }


def extract_text_output(response_payload: Mapping[str, Any]) -> str:
    """Extract text from a Responses API payload across a few known shapes."""
    output_text = response_payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    texts: list[str] = []
    for item in response_payload.get("output", []) or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, Mapping):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
                continue
            json_payload = content.get("json")
            if isinstance(json_payload, (dict, list)):
                texts.append(json.dumps(json_payload, ensure_ascii=False))

    if texts:
        return "\n".join(texts)

    raise ValueError(
        "Macaron response did not contain text output in expected fields "
        "(`output_text` or `output[*].content[*].text`)."
    )


def extract_token_usage(response_payload: Mapping[str, Any]) -> Tuple[int, int]:
    """Best-effort token usage extraction from Responses API payloads."""
    usage = response_payload.get("usage")
    if not isinstance(usage, Mapping):
        return 0, 0

    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    try:
        return int(input_tokens or 0), int(output_tokens or 0)
    except (TypeError, ValueError):
        return 0, 0


def _parse_event_stream_block(block: str) -> tuple[str | None, Any]:
    """Parse one SSE-style event block from a Macaron transcript wrapper."""
    event_name: str | None = None
    data_lines: list[str] = []

    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())

    if not data_lines:
        return event_name, None

    data_text = "\n".join(data_lines)
    try:
        return event_name, json.loads(data_text)
    except json.JSONDecodeError:
        return event_name, data_text


def normalize_response_payload(raw_payload: Any) -> Dict[str, Any]:
    """Normalize Macaron responses across direct JSON and transcript wrappers."""
    if isinstance(raw_payload, Mapping):
        return dict(raw_payload)

    if isinstance(raw_payload, str):
        transcript = raw_payload.strip()
        if not transcript:
            raise ValueError("Macaron returned an empty response payload.")

        if not transcript.startswith("event:"):
            parsed = parse_json_text(transcript)
            if isinstance(parsed, Mapping):
                return dict(parsed)
            raise ValueError("Macaron string payload did not decode to an object response.")

        response_obj: Dict[str, Any] = {}
        output_items: list[Any] = []
        output_text: str | None = None

        for block in transcript.split("\n\n"):
            if not block.strip():
                continue

            event_name, event_payload = _parse_event_stream_block(block)
            if isinstance(event_payload, Mapping):
                response = event_payload.get("response")
                if isinstance(response, Mapping):
                    response_obj = dict(response)

                if event_payload.get("type") == "response.output_item.done":
                    item = event_payload.get("item")
                    if isinstance(item, Mapping):
                        output_items.append(dict(item))

                if event_payload.get("type") == "response.output_text.done":
                    text = event_payload.get("text")
                    if isinstance(text, str) and text.strip():
                        output_text = text

            elif event_name == "response.output_text.done" and isinstance(event_payload, str) and event_payload.strip():
                output_text = event_payload

        if output_items and not response_obj.get("output"):
            response_obj["output"] = output_items
        if output_text and not response_obj.get("output_text"):
            response_obj["output_text"] = output_text
        if output_text and not response_obj.get("output"):
            response_obj["output"] = [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output_text,
                        }
                    ],
                }
            ]

        if response_obj:
            return response_obj

    raise ValueError(f"Unsupported Macaron response payload type: {type(raw_payload).__name__}")


def build_schema_guided_prompt(prompt: str, schema: Dict[str, Any]) -> str:
    """Add an explicit JSON-only instruction as a fallback for flaky gateways."""
    schema_text = json.dumps(_tighten_schema(schema), ensure_ascii=False, separators=(",", ":"))
    return (
        prompt.rstrip()
        + "\n\nReturn ONLY a valid JSON object that matches this schema exactly."
        + " Do not add prose, markdown, or code fences.\n"
        + schema_text
    )


def parse_json_text(text_payload: str) -> Any:
    """Parse the first JSON value from a model text payload.

    Macaron sometimes appends short explanatory prose after an otherwise valid
    JSON object, so we decode only the first JSON value instead of requiring the
    entire text blob to be pure JSON.
    """
    decoder = json.JSONDecoder()

    def _try_decode(candidate: str) -> Any:
        obj, _end = decoder.raw_decode(candidate.lstrip())
        return obj

    stripped = (text_payload or "").strip()
    if not stripped:
        raise ValueError("Macaron returned an empty text payload; expected JSON content.")

    try:
        return _try_decode(stripped)
    except json.JSONDecodeError:
        pass

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text_payload, flags=re.IGNORECASE):
        fenced = match.group(1).strip()
        if not fenced:
            continue
        try:
            return _try_decode(fenced)
        except json.JSONDecodeError:
            continue

    for idx, char in enumerate(text_payload):
        if char not in "{[":
            continue
        try:
            return _try_decode(text_payload[idx:])
        except json.JSONDecodeError:
            continue

    raise ValueError("Macaron text payload did not contain a decodable JSON object or array.")


def call_macaron_json(
    prompt: str,
    schema: Dict[str, Any],
    *,
    schema_name: str = "response_schema",
    model: str = DEFAULT_MACARON_MODEL,
    url: str | None = None,
    api_key: str | None = None,
    timeout: int = DEFAULT_MACARON_TIMEOUT_SECONDS,
) -> tuple[Any, Dict[str, Any]]:
    """Call the Macaron Responses API and parse the JSON text payload."""
    response = requests.post(
        get_macaron_base_url(url),
        headers={
            "Authorization": f"Bearer {get_macaron_api_key(api_key)}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=build_macaron_payload(prompt, schema_name, schema, model=model),
        timeout=timeout,
    )
    response.raise_for_status()
    raw_payload = normalize_response_payload(response.json())
    text_payload = extract_text_output(raw_payload)
    return parse_json_text(text_payload), raw_payload


def call_macaron_pydantic(
    prompt: str,
    model_cls: Type[BaseModel],
    *,
    schema_name: str | None = None,
    model: str = DEFAULT_MACARON_MODEL,
    url: str | None = None,
    api_key: str | None = None,
    timeout: int = DEFAULT_MACARON_TIMEOUT_SECONDS,
) -> tuple[BaseModel, Dict[str, Any]]:
    """Call the Macaron Responses API and validate the parsed JSON to a model."""
    schema = build_pydantic_schema(model_cls)
    guided_prompt = build_schema_guided_prompt(prompt, schema)
    parsed, raw_payload = call_macaron_json(
        guided_prompt,
        schema,
        schema_name=schema_name or model_cls.__name__,
        model=model,
        url=url,
        api_key=api_key,
        timeout=timeout,
    )
    return model_cls.model_validate(parsed), raw_payload
