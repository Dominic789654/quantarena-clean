import ast
import json
import os
import re
import sys
import threading
import types
from typing import Dict, Any, Optional, Type, Union, get_args, get_origin
from dataclasses import dataclass
from pydantic import BaseModel
from llm.provider import Provider
from util.logger import logger

# Add deepear path for stats import
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEEPEAR_SRC = os.path.join(PROJECT_ROOT, "deepear", "src")
if DEEPEAR_SRC not in sys.path:
    sys.path.insert(0, DEEPEAR_SRC)

try:
    from deepear.src.utils.stats import get_stats
    STATS_ENABLED = True
except ImportError:
    STATS_ENABLED = False

# Token usage tracking for backtest
_token_lock = threading.Lock()
_token_scope_local = threading.local()
_scope_token_trackers: Dict[str, Dict[str, Any]] = {}


def _empty_token_tracker() -> Dict[str, Any]:
    return {
        "total_input": 0,
        "total_output": 0,
        "calls": 0,
        "by_agent": {},
    }


_token_tracker = _empty_token_tracker()


def _copy_token_tracker(stats: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    stats = stats or _empty_token_tracker()
    return {
        "total_input": stats.get("total_input", 0),
        "total_output": stats.get("total_output", 0),
        "calls": stats.get("calls", 0),
        "by_agent": {
            agent: {
                "input": agent_stats.get("input", 0),
                "output": agent_stats.get("output", 0),
                "calls": agent_stats.get("calls", 0),
            }
            for agent, agent_stats in (stats.get("by_agent") or {}).items()
        },
    }


def _apply_token_usage(stats: Dict[str, Any], agent_name: str, input_tokens: int, output_tokens: int) -> None:
    stats["total_input"] += input_tokens
    stats["total_output"] += output_tokens
    stats["calls"] += 1

    by_agent = stats.setdefault("by_agent", {})
    if agent_name not in by_agent:
        by_agent[agent_name] = {"input": 0, "output": 0, "calls": 0}
    by_agent[agent_name]["input"] += input_tokens
    by_agent[agent_name]["output"] += output_tokens
    by_agent[agent_name]["calls"] += 1


def set_token_scope(scope_name: Optional[str]) -> None:
    """Bind token accounting to a named scope for the current thread."""
    _token_scope_local.scope_name = scope_name


def get_token_scope() -> Optional[str]:
    """Return the current token scope for this thread."""
    return getattr(_token_scope_local, "scope_name", None)


def reset_token_tracker(scope_name: Optional[str] = None):
    """Reset token tracker globally or for a specific scope."""
    global _token_tracker, _scope_token_trackers
    with _token_lock:
        if scope_name is None:
            _token_tracker = _empty_token_tracker()
            _scope_token_trackers = {}
            return
        _scope_token_trackers[scope_name] = _empty_token_tracker()


def get_token_stats(scope_name: Optional[str] = None) -> Dict[str, Any]:
    """Get current token statistics globally or for a specific scope."""
    with _token_lock:
        if scope_name is None:
            return _copy_token_tracker(_token_tracker)
        return _copy_token_tracker(_scope_token_trackers.get(scope_name))


def record_token_usage(agent_name: str, input_tokens: int, output_tokens: int, provider: str = "deepseek"):
    """Record token usage for an agent call."""
    global _token_tracker
    scope_name = get_token_scope()
    with _token_lock:
        _apply_token_usage(_token_tracker, agent_name, input_tokens, output_tokens)
        if scope_name:
            scoped = _scope_token_trackers.setdefault(scope_name, _empty_token_tracker())
            _apply_token_usage(scoped, agent_name, input_tokens, output_tokens)

    # Also record to global stats if available
    if STATS_ENABLED:
        get_stats().record_tokens(provider, input_tokens, output_tokens)


def _estimate_tokens(prompt: str, response_text: str = "") -> tuple[int, int]:
    """Best-effort token estimation when provider metadata is unavailable."""
    prompt_chars = len(prompt) if prompt else 0
    response_chars = len(response_text) if response_text else 0
    return max(1, prompt_chars // 3), max(1, response_chars // 3 or 1)


def _strip_json_comments(text: str) -> str:
    """Remove // and /* */ comments while preserving quoted strings."""
    result = []
    i = 0
    n = len(text)
    in_string = False
    escape = False

    while i < n:
        char = text[i]

        if in_string:
            result.append(char)
            if char == "\\" and not escape:
                escape = True
            elif char == '"' and not escape:
                in_string = False
            else:
                escape = False
            i += 1
            continue

        if char == '"':
            in_string = True
            escape = False
            result.append(char)
            i += 1
            continue

        if i + 1 < n and text[i:i + 2] == "//":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue

        if i + 1 < n and text[i:i + 2] == "/*":
            i += 2
            while i + 1 < n and text[i:i + 2] != "*/":
                i += 1
            i += 2
            continue

        result.append(char)
        i += 1

    return "".join(result)


def _extract_json_candidate(text: str) -> Optional[Any]:
    """Extract the first JSON-like object/list from free-form model output."""
    if not text:
        return None

    candidate = text.strip()
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", candidate, re.DOTALL)
    if md_match:
        candidate = md_match.group(1).strip()
    elif candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\n?", "", candidate)
        candidate = re.sub(r"\n?```\s*$", "", candidate)

    start_brace = candidate.find("{")
    start_bracket = candidate.find("[")
    if start_brace == -1 and start_bracket == -1:
        return None
    start_idx = start_brace if (start_bracket == -1 or (start_brace != -1 and start_brace < start_bracket)) else start_bracket
    candidate = _strip_json_comments(candidate[start_idx:].strip())

    # Fix a few common key quoting issues from weaker models.
    candidate = re.sub(r'([\{,]\s*)([a-zA-Z_]\w*)"\s*:', r'\1"\2":', candidate)
    candidate = re.sub(r'([\{,]\s*)"([a-zA-Z_]\w*)\s*:', r'\1"\2":', candidate)
    candidate = re.sub(r'([\{,]\s*)([a-zA-Z_]\w*)\s*:', r'\1"\2":', candidate)
    candidate = re.sub(r",\s*([\]}])", r"\1", candidate)

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(candidate)
        return obj
    except json.JSONDecodeError:
        pass

    try:
        fixed_quotes = re.sub(r"'(.*?)':", r'"\1":', candidate)
        fixed_quotes = re.sub(r':\s*\'(.*?)\'', r': "\1"', fixed_quotes)
        obj, _ = decoder.raw_decode(fixed_quotes)
        return obj
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        stack = []
        for idx, char in enumerate(candidate):
            if char == "{":
                stack.append("{")
            elif char == "}":
                if stack:
                    stack.pop()
                if not stack:
                    return ast.literal_eval(candidate[: idx + 1])
    except (ValueError, SyntaxError, MemoryError):
        return None

    return None


def _response_to_text(raw_response: Any) -> str:
    """Flatten common message/content shapes to plain text for parsing."""
    if raw_response is None:
        return ""

    content = getattr(raw_response, "content", raw_response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(part for part in parts if part)
    return str(content)


def _validate_raw_response(raw_response: Any, model_cls: Type[BaseModel]) -> Optional[BaseModel]:
    """Validate raw provider output against a Pydantic schema."""
    if isinstance(raw_response, model_cls):
        return raw_response

    if isinstance(raw_response, dict):
        try:
            return model_cls.model_validate(raw_response)
        except Exception:
            return None

    response_text = _response_to_text(raw_response).strip()
    if not response_text:
        return None

    try:
        return model_cls.model_validate_json(response_text)
    except Exception:
        pass

    extracted = _extract_json_candidate(response_text)
    if extracted is None:
        return None

    try:
        return model_cls.model_validate(extracted)
    except Exception:
        return None


def _json_output_example(model_cls: Type[BaseModel]) -> Dict[str, Any]:
    """Build a compact JSON example for provider JSON-mode prompts."""
    try:
        example = _safe_model_fallback(model_cls).model_dump(mode="json")
        return example if isinstance(example, dict) else {}
    except Exception:
        return {field_name: None for field_name in getattr(model_cls, "model_fields", {})}


def _compact_json_schema(model_cls: Type[BaseModel]) -> Dict[str, Any]:
    """Return only field-level schema details that are useful in a prompt."""
    try:
        schema = model_cls.model_json_schema()
    except Exception:
        return {}

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return schema if isinstance(schema, dict) else {}

    required = set(schema.get("required") or [])
    compact: Dict[str, Any] = {}
    for field_name, metadata in properties.items():
        if not isinstance(metadata, dict):
            compact[field_name] = {"required": field_name in required}
            continue
        field_schema: Dict[str, Any] = {"required": field_name in required}
        for key in ("type", "description", "enum", "anyOf", "$ref"):
            if key in metadata:
                field_schema[key] = metadata[key]
        compact[field_name] = field_schema
    return compact


def _build_json_output_prompt(prompt: str, model_cls: Type[BaseModel]) -> str:
    """
    Add provider-visible JSON instructions for APIs that require prompt guidance.

    DeepSeek JSON Output requires response_format={"type": "json_object"} plus
    the word "json" and a concrete JSON example in the prompt. LangChain sets
    response_format for json_mode; this wrapper supplies the prompt contract.
    """
    example = json.dumps(_json_output_example(model_cls), ensure_ascii=False, indent=2)
    schema = json.dumps(_compact_json_schema(model_cls), ensure_ascii=False, separators=(",", ":"))
    return (
        "Return only valid JSON. Do not include markdown fences, comments, or explanatory text. "
        "The JSON object must match the requested schema and use the exact field names.\n\n"
        "EXAMPLE JSON OUTPUT:\n"
        f"{example}\n\n"
        "JSON SCHEMA FIELDS:\n"
        f"{schema}\n\n"
        "USER TASK:\n"
        f"{prompt}"
    )


def _structured_prompt_for_method(
    prompt: str,
    method: str,
    provider: str,
    model_cls: Type[BaseModel],
) -> str:
    if method == "json_mode" and provider == "deepseek":
        return _build_json_output_prompt(prompt, model_cls)
    return prompt


def _structured_methods_for_provider(provider: str, model_id: str) -> list[str]:
    if provider == "deepseek":
        return ["json_mode"]
    if "doubao" in model_id or "seed" in model_id:
        return ["json_mode", "function_calling"]
    if "qwen" in model_id or provider in ["alibaba", "dashscope"]:
        return ["json_mode"]
    return ["function_calling", "json_mode"]

def _default_value_for_field(field_name: str, annotation: Any) -> Any:
    """Generate a safe placeholder for required Pydantic fields."""
    lower_name = field_name.lower()
    origin = get_origin(annotation)

    if origin is None:
        if annotation is str:
            if "action" in lower_name:
                return "HOLD"
            if "signal" in lower_name:
                return "NEUTRAL"
            if "reason" in lower_name or "justification" in lower_name:
                return "Fallback due to LLM error"
            return ""
        if annotation is int:
            return 0
        if annotation is float:
            return 0.0
        if annotation is bool:
            return False
        if annotation is dict:
            return {}
        if annotation is list:
            return []

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return _safe_model_fallback(annotation)

        return None

    args = get_args(annotation)
    if origin in (list, set, tuple):
        return []
    if origin is dict:
        return {}
    if origin in (Union, types.UnionType):
        non_none = [arg for arg in args if arg is not type(None)]
        if not non_none:
            return None
        return _default_value_for_field(field_name, non_none[0])

    # Fallback for uncommon typing annotations.
    return None


def _safe_model_fallback(model_cls: Type[BaseModel]) -> BaseModel:
    """
    Build a fallback model safely, even when required fields have no defaults.

    Uses generated placeholders first; if validation still fails, falls back to
    `model_construct` to avoid raising in failure paths.
    """
    try:
        return model_cls()
    except Exception:
        fallback_data: Dict[str, Any] = {}
        for field_name, field in model_cls.model_fields.items():
            if field.default_factory is not None:
                fallback_data[field_name] = field.default_factory()
            elif not field.is_required():
                fallback_data[field_name] = field.default
            else:
                fallback_data[field_name] = _default_value_for_field(field_name, field.annotation)

        try:
            return model_cls.model_validate(fallback_data)
        except Exception:
            try:
                return model_cls.model_construct(**fallback_data)
            except Exception:
                return model_cls.model_construct()


@dataclass
class LLMConfig:
    """Configuration for LLM inference"""
    provider: str
    model: str
    temperature: float = 0.5
    max_retries: int = 3


def get_model(config: LLMConfig):
    """Get a model instance based on configuration."""

    provider = Provider.from_string(config.provider)
    model_config = provider.config

    if model_config.requires_api_key:
        api_key = model_config.resolve_api_key()
        if not api_key:
            expected = ", ".join(model_config.credentials.api_key_envs)
            logger.error(f"API Key Error: Please make sure one of [{expected}] is set in your .env file.")
            raise ValueError(f"{provider} API key not found. Please set one of [{expected}] in .env file.")

    kwargs = {
        "model": config.model,
        **({"api_key": api_key} if model_config.requires_api_key else {}),
        **({"base_url": model_config.base_url} if model_config.base_url else {}),
        **({"temperature": config.temperature} if config.temperature is not None else {})
    }

    # Add thinking parameter for Ark/Seed models
    if provider == Provider.ARK:
        kwargs["extra_body"] = {
            "thinking": {
                "type": "disabled"  # 不使用深度思考能力
            }
        }

    try:
        return model_config.model_class(**kwargs)
    except Exception as e:
        logger.error(f"{provider} Chat Error: {e}")
        raise ValueError(f"{provider} Chat Error: {e}")


def agent_call(
    prompt: str,
    llm_config: Dict[str, Any],
    pydantic_model: Type[BaseModel],
    agent_name: str = "unknown",
):
    """
    Makes an agent call with retry logic and structured output.

    Args:
        prompt: The prompt to send to the LLM
        llm_config: Configuration for the LLM
        pydantic_model: The Pydantic model to use for structured output
        agent_name: Name of the agent for token tracking
    Returns:
        An instance of pydantic_model (with defaults if error occurs)
    """
    llm_cfg = LLMConfig(**llm_config)
    provider_name = llm_config.get("provider", "deepseek")

    try:
        llm = get_model(llm_cfg)
    except Exception as e:
        logger.error(f"Model initialization failed: {e}")
        estimated_input, estimated_output = _estimate_tokens(prompt, str(e))
        record_token_usage(agent_name, estimated_input, estimated_output, provider_name)
        return _safe_model_fallback(pydantic_model)

    model_id = llm_config.get("model", "").lower()
    provider = llm_config.get("provider", "").lower()
    structured_methods = _structured_methods_for_provider(provider, model_id)

    for attempt in range(llm_cfg.max_retries):
        # Try structured methods first
        for method in structured_methods:
            try:
                llm_structured = llm.with_structured_output(pydantic_model, method=method)
                structured_prompt = _structured_prompt_for_method(prompt, method, provider, pydantic_model)
                result = llm_structured.invoke(structured_prompt)
                if result is None:
                    raise ValueError("LLM returned None")

                # Try to estimate tokens based on prompt and response length
                response_str = str(result.model_dump()) if hasattr(result, 'model_dump') else str(result)
                estimated_input, estimated_output = _estimate_tokens(structured_prompt, response_str)

                try:
                    raw_response = llm.invoke(structured_prompt)
                    if hasattr(raw_response, 'usage_metadata') and raw_response.usage_metadata:
                        estimated_input = raw_response.usage_metadata.get('input_tokens', estimated_input)
                        estimated_output = raw_response.usage_metadata.get('output_tokens', estimated_output)
                    elif hasattr(raw_response, 'response_metadata'):
                        usage = raw_response.response_metadata.get('token_usage', {})
                        if usage:
                            estimated_input = usage.get('prompt_tokens', estimated_input)
                            estimated_output = usage.get('completion_tokens', estimated_output)
                except Exception:
                    pass

                record_token_usage(agent_name, estimated_input, estimated_output, provider_name)

                return result
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{llm_cfg.max_retries}, method {method} failed: {e}")
                continue

        # Structured methods failed - try raw text with fallback
        try:
            logger.warning(f"Attempt {attempt + 1}/{llm_cfg.max_retries}: All structured methods failed, trying raw text fallback")
            fallback_prompt = _build_json_output_prompt(prompt, pydantic_model) if provider == "deepseek" else prompt
            raw_response = llm.invoke(fallback_prompt)

            # Try to estimate tokens
            response_str = _response_to_text(raw_response)
            estimated_input, estimated_output = _estimate_tokens(fallback_prompt, response_str)

            record_token_usage(agent_name, estimated_input, estimated_output, provider_name)

            validated = _validate_raw_response(raw_response, pydantic_model)
            if validated is not None:
                logger.info("Raw text JSON fallback validated successfully")
                return validated

            # Return default model (caller should handle this)
            logger.warning("Raw text fallback could not be validated, returning default model")
            return _safe_model_fallback(pydantic_model)

        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{llm_cfg.max_retries} failed for all methods: {e}")

    logger.error(f"All {llm_cfg.max_retries} attempts failed")
    estimated_input, estimated_output = _estimate_tokens(prompt, "LLM call failed")
    record_token_usage(agent_name, estimated_input, estimated_output, provider_name)
    return _safe_model_fallback(pydantic_model)
