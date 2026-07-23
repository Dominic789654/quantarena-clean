from dataclasses import dataclass
from enum import Enum
from typing import Optional, Type

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel

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
    env_key: Optional[str] = None
    base_url: Optional[str] = None
    requires_api_key: bool = True

class Provider(str, Enum):
    """Supported LLM providers"""
    OPENAI = "OpenAI"
    ANTHROPIC = "Anthropic"
    DEEPSEEK = "DeepSeek"
    ALIBABA = "Alibaba"
    DASHSCOPE = "DashScope"
    ZHIPU = "ZhiPu"
    OLLAMA = "Ollama"
    FIREWORKS= "Fireworks"
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
        PROVIDER_CONFIGS = {
            Provider.OPENAI: ModelConfig(
                model_class=ChatOpenAI,
                env_key="OPENAI_API_KEY",
            ),
            Provider.ANTHROPIC: ModelConfig(
                model_class=ChatAnthropic,
                env_key="ANTHROPIC_API_KEY",
            ),
            Provider.DEEPSEEK: ModelConfig(
                model_class=ChatDeepSeek,
                env_key="DEEPSEEK_API_KEY",
            ),
            Provider.ALIBABA: ModelConfig(
                model_class=ChatOpenAI,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                env_key="QWEN_API_KEY",
            ),
            Provider.DASHSCOPE: ModelConfig(
                model_class=ChatOpenAI,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                env_key="DASHSCOPE_API_KEY",
            ),
            Provider.ZHIPU: ModelConfig(
                model_class=ChatOpenAI,
                base_url="https://open.bigmodel.cn/api/paas/v4",
                env_key="ZHIPU_API_KEY",
            ),
            Provider.OLLAMA: ModelConfig(
                model_class=ChatOllama,
                requires_api_key=False,
            ),
        }
        # Add Fireworks only if available
        if HAS_FIREWORKS and ChatFireworks is not None:
            PROVIDER_CONFIGS[Provider.FIREWORKS] = ModelConfig(
                model_class=ChatFireworks,
                env_key="FIREWORKS_API_KEY",
            )
        # Add YiZhan and AiHubMix
        PROVIDER_CONFIGS[Provider.YIZHAN] = ModelConfig(
            model_class=ChatOpenAI,
            env_key="YIZHAN_API_KEY",
            base_url="https://vip.yi-zhan.top/v1",
        )
        PROVIDER_CONFIGS[Provider.AIHUBMIX] = ModelConfig(
            model_class=ChatOpenAI,
            env_key="AIHUBMIX_API_KEY",
            base_url="https://api.aihubmix.com/v1",
        )
        PROVIDER_CONFIGS[Provider.ARK] = ModelConfig(
            model_class=ChatOpenAI,
            env_key="ARK_API_KEY",
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        )
        PROVIDER_CONFIGS[Provider.LOCAL] = ModelConfig(
            model_class=ChatOpenAI,
            env_key="LOCAL_API_KEY",
            base_url="http://127.0.0.1:12580/tingly/openai",
        )
        return PROVIDER_CONFIGS[self]
