"""
LLM Model Factory
=================

Factory to get the appropriate LLM model based on provider configuration.
Uses a configuration-driven approach for easy provider addition.

Supported providers:
- openai: OpenAI GPT models
- ollama: Local Ollama models
- deepseek: DeepSeek models
- dashscope/alibaba: Alibaba Qwen models
- openrouter: OpenRouter API
- zai: Z.ai API
- ust: UST API
- ark: Volcengine Ark API
- local: Local OpenAI-compatible models
"""

import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from loguru import logger

from agno.models.openai import OpenAIChat
from agno.models.ollama import Ollama
from agno.models.dashscope import DashScope
from agno.models.deepseek import DeepSeek
from agno.models.openrouter import OpenRouter

# Credential knowledge (API-key env vars, base URLs) is shared with the
# deepfund langchain provider registry; only agno model classes live here.
from shared.config.llm_providers import get_provider_credentials


# Standard role map for OpenAI-compatible providers
STANDARD_ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}


@dataclass
class ProviderConfig:
    """Configuration for a model provider."""
    model_class: Any  # The model class to instantiate
    api_key_env: Optional[str] = None  # Environment variable for API key
    base_url: Optional[str] = None  # Default base URL for API
    base_url_env: Optional[str] = None  # Environment variable for base URL
    requires_role_map: bool = False  # Whether to use standard role map
    extra_kwargs: Dict[str, Any] = field(default_factory=dict)  # Additional kwargs

    def get_api_key(self, provider_key: str = "") -> Optional[str]:
        """Get API key: shared credential registry first, local env fallback."""
        creds = get_provider_credentials(provider_key) if provider_key else None
        if creds is not None and creds.requires_api_key:
            key = creds.resolve_api_key()
            if not key:
                logger.warning(f"None of [{', '.join(creds.api_key_envs)}] set")
            return key
        if self.api_key_env:
            key = os.getenv(self.api_key_env)
            if not key:
                logger.warning(f"{self.api_key_env} not set")
            return key
        return None

    def get_base_url(self, provider_key: str = "") -> Optional[str]:
        """Get base URL: env override first, then this provider's default."""
        creds = get_provider_credentials(provider_key) if provider_key else None
        if creds is not None:
            return creds.resolve_base_url(default=self.base_url)
        if self.base_url_env:
            return os.getenv(self.base_url_env, self.base_url)
        return self.base_url


# Provider configuration registry
PROVIDERS: Dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        model_class=OpenAIChat,
    ),
    "ollama": ProviderConfig(
        model_class=Ollama,
    ),
    "deepseek": ProviderConfig(
        model_class=DeepSeek,
        api_key_env="DEEPSEEK_API_KEY",
    ),
    "dashscope": ProviderConfig(
        model_class=DashScope,
        api_key_env="DASHSCOPE_API_KEY",  # Also checks QWEN_API_KEY as fallback
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    "alibaba": ProviderConfig(
        model_class=DashScope,
        api_key_env="DASHSCOPE_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    "openrouter": ProviderConfig(
        model_class=OpenRouter,
        api_key_env="OPENROUTER_API_KEY",
    ),
    "zai": ProviderConfig(
        model_class=OpenAIChat,
        api_key_env="ZAI_KEY_API",
        base_url="https://api.z.ai/api/paas/v4",
        requires_role_map=True,
        extra_kwargs={"timeout": 60, "extra_body": {"enable_thinking": False}},
    ),
    "ust": ProviderConfig(
        model_class=OpenAIChat,
        api_key_env="UST_KEY_API",
        base_url_env="UST_URL",
        requires_role_map=True,
        extra_kwargs={"extra_body": {"enable_thinking": False}},
    ),
    "ark": ProviderConfig(
        model_class=OpenAIChat,
        api_key_env="ARK_API_KEY",
        base_url_env="ARK_BASE_URL",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        requires_role_map=True,
    ),
    "local": ProviderConfig(
        model_class=OpenAIChat,
        api_key_env="LOCAL_API_KEY",
        base_url_env="LOCAL_BASE_URL",
        base_url="http://127.0.0.1:12580/tingly/openai",
        requires_role_map=True,
    ),
}


def get_model(model_provider: str, model_id: str, **kwargs) -> Any:
    """
    Factory to get the appropriate LLM model.

    Args:
        model_provider: Provider name (e.g., "openai", "ollama", "deepseek")
        model_id: The specific model ID (e.g., "gpt-4o", "llama3", "deepseek-chat")
        **kwargs: Additional arguments passed to the model constructor

    Returns:
        Configured model instance

    Raises:
        ValueError: If provider is unknown
    """
    provider_key = model_provider.lower()

    if provider_key not in PROVIDERS:
        raise ValueError(f"Unknown model provider: {model_provider}. "
                        f"Available: {list(PROVIDERS.keys())}")

    config = PROVIDERS[provider_key]

    # Build kwargs for model instantiation
    model_kwargs = {}

    # Add API key if required (shared registry handles fallbacks such as
    # QWEN_API_KEY / DASHSCOPE_API_KEY for the Alibaba providers)
    api_key = config.get_api_key(provider_key)
    if api_key:
        model_kwargs["api_key"] = api_key

    # Add base URL
    base_url = config.get_base_url(provider_key)
    if base_url:
        model_kwargs["base_url"] = base_url

    # Add role map for OpenAI-compatible providers
    if config.requires_role_map:
        role_map = kwargs.pop("role_map", STANDARD_ROLE_MAP)
        model_kwargs["role_map"] = role_map

    # Add extra kwargs from config
    model_kwargs.update(config.extra_kwargs)

    # Override with user-provided kwargs
    model_kwargs.update(kwargs)

    return config.model_class(id=model_id, **model_kwargs)


def register_provider(name: str, config: ProviderConfig) -> None:
    """
    Register a new provider configuration.

    Args:
        name: Provider name (will be lowercased)
        config: Provider configuration
    """
    PROVIDERS[name.lower()] = config


def list_providers() -> list:
    """Return list of available provider names."""
    return list(PROVIDERS.keys())
