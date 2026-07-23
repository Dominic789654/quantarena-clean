"""Canonical LLM provider credential registry.

Single source of truth for *credential knowledge* — which env vars hold a
provider's API key (with fallbacks) and which base URL / URL-override env
applies. Model-class construction stays in the consumers, because the two
stacks legitimately differ (deepfund/src/llm builds langchain chat models,
deepear/src/utils/llm builds agno models).

Divergences that are intentional and must NOT be silently unified:
- ark: deepfund targets the coding endpoint (/api/coding/v3) while deepear
  targets the standard endpoint (/api/v3). Consumers pass their own
  default_base_url; both honor the ARK_BASE_URL override.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ProviderCredentials:
    """Credential lookup spec for one provider (case-insensitive key)."""

    api_key_envs: Tuple[str, ...] = ()
    base_url: Optional[str] = None
    base_url_env: Optional[str] = None

    @property
    def requires_api_key(self) -> bool:
        return bool(self.api_key_envs)

    @property
    def primary_key_env(self) -> Optional[str]:
        return self.api_key_envs[0] if self.api_key_envs else None

    def resolve_api_key(self) -> Optional[str]:
        """First non-empty key among the configured env vars."""
        for env in self.api_key_envs:
            value = os.getenv(env, "").strip()
            if value:
                return value
        return None

    def resolve_base_url(self, default: Optional[str] = None) -> Optional[str]:
        """Env override first, then the consumer's default, then the registry default."""
        if self.base_url_env:
            override = os.getenv(self.base_url_env, "").strip()
            if override:
                return override
        return default or self.base_url


PROVIDER_CREDENTIALS: dict[str, ProviderCredentials] = {
    "openai": ProviderCredentials(api_key_envs=("OPENAI_API_KEY",)),
    "anthropic": ProviderCredentials(api_key_envs=("ANTHROPIC_API_KEY",)),
    "deepseek": ProviderCredentials(api_key_envs=("DEEPSEEK_API_KEY",)),
    "alibaba": ProviderCredentials(
        api_key_envs=("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    "dashscope": ProviderCredentials(
        api_key_envs=("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    "zhipu": ProviderCredentials(
        api_key_envs=("ZHIPU_API_KEY",),
        base_url="https://open.bigmodel.cn/api/paas/v4",
    ),
    "ollama": ProviderCredentials(),
    "fireworks": ProviderCredentials(api_key_envs=("FIREWORKS_API_KEY",)),
    "yizhan": ProviderCredentials(
        api_key_envs=("YIZHAN_API_KEY",),
        base_url="https://vip.yi-zhan.top/v1",
    ),
    "aihubmix": ProviderCredentials(
        api_key_envs=("AIHUBMIX_API_KEY",),
        base_url="https://api.aihubmix.com/v1",
    ),
    "ark": ProviderCredentials(
        api_key_envs=("ARK_API_KEY",),
        base_url_env="ARK_BASE_URL",
        # No registry default on purpose: deepfund and deepear intentionally
        # target different Ark endpoints (see module docstring).
    ),
    "local": ProviderCredentials(
        api_key_envs=("LOCAL_API_KEY",),
        base_url="http://127.0.0.1:12580/tingly/openai",
        base_url_env="LOCAL_BASE_URL",
    ),
    "openrouter": ProviderCredentials(api_key_envs=("OPENROUTER_API_KEY",)),
    "zai": ProviderCredentials(
        api_key_envs=("ZAI_KEY_API",),
        base_url="https://api.z.ai/api/paas/v4",
    ),
    "ust": ProviderCredentials(api_key_envs=("UST_KEY_API",), base_url_env="UST_URL"),
}


def get_provider_credentials(provider: str) -> Optional[ProviderCredentials]:
    """Look up a provider's credential spec (case-insensitive)."""
    return PROVIDER_CREDENTIALS.get(provider.strip().lower())
