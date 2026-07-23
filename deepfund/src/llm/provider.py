from dataclasses import dataclass
from enum import Enum
from typing import Optional, Type

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel

# Credential knowledge (API-key env vars, base URLs) is shared with the
# deepear model factory; only the langchain model classes live here.
from shared.config.llm_providers import ProviderCredentials, get_provider_credentials

# Optional imports with fallback
try:
    from langchain_fireworks import ChatFireworks
    HAS_FIREWORKS = True
except ImportError:
    ChatFireworks = None
    HAS_FIREWORKS = False


@dataclass
class ModelConfig:
    """Configuration for a model provider"""
    model_class: Optional[Type[BaseChatModel]]
    credentials: ProviderCredentials
    base_url: Optional[str] = None

    @property
    def requires_api_key(self) -> bool:
        return self.credentials.requires_api_key

    @property
    def env_key(self) -> Optional[str]:
        return self.credentials.primary_key_env

    def resolve_api_key(self) -> Optional[str]:
        return self.credentials.resolve_api_key()


# deepfund intentionally targets Ark's coding endpoint; deepear uses the
# standard /api/v3 endpoint. Both honor the ARK_BASE_URL env override.
_ARK_CODING_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"


class Provider(str, Enum):
    """Supported LLM providers"""
    OPENAI = "OpenAI"
    ANTHROPIC = "Anthropic"
    DEEPSEEK = "DeepSeek"
    ALIBABA = "Alibaba"
    DASHSCOPE = "DashScope"
    ZHIPU = "ZhiPu"
    OLLAMA = "Ollama"
    FIREWORKS = "Fireworks"
    YIZHAN = "YiZhan"
    AIHUBMIX = "AiHubMix"
    ARK = "Ark"
    LOCAL = "Local"

    @classmethod
    def from_string(cls, value: str) -> "Provider":
        """Get provider from string (case-insensitive)."""
        value_lower = value.lower()
        for member in cls:
            if member.value.lower() == value_lower:
                return member
        raise ValueError(f"'{value}' is not a valid Provider")

    @property
    def config(self) -> ModelConfig:
        """Get the configuration for this provider"""
        model_classes = {
            Provider.OPENAI: ChatOpenAI,
            Provider.ANTHROPIC: ChatAnthropic,
            Provider.DEEPSEEK: ChatDeepSeek,
            Provider.ALIBABA: ChatOpenAI,
            Provider.DASHSCOPE: ChatOpenAI,
            Provider.ZHIPU: ChatOpenAI,
            Provider.OLLAMA: ChatOllama,
            Provider.YIZHAN: ChatOpenAI,
            Provider.AIHUBMIX: ChatOpenAI,
            Provider.ARK: ChatOpenAI,
            Provider.LOCAL: ChatOpenAI,
        }
        if HAS_FIREWORKS and ChatFireworks is not None:
            model_classes[Provider.FIREWORKS] = ChatFireworks

        model_class = model_classes.get(self)
        if model_class is None:
            raise ValueError(f"Provider {self.value} is unavailable (missing optional dependency)")

        credentials = get_provider_credentials(self.value)
        if credentials is None:
            raise ValueError(f"No credential registry entry for provider {self.value}")

        default_base_url = _ARK_CODING_BASE_URL if self is Provider.ARK else None
        return ModelConfig(
            model_class=model_class,
            credentials=credentials,
            base_url=credentials.resolve_base_url(default=default_base_url),
        )
