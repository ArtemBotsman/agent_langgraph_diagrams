"""Provider-aware construction of instrumented LLM clients."""

from __future__ import annotations

import os

from traceable_spec.llm.anthropic import AnthropicConfig, AnthropicLLMClient
from traceable_spec.llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)

ProviderConfig = AnthropicConfig | OpenAICompatibleConfig
InstrumentedLLMClient = AnthropicLLMClient | OpenAICompatibleLLMClient


def provider_config_from_env() -> ProviderConfig:
    """Load the native config selected by ``LLM_PROVIDER``."""

    provider = os.environ.get("LLM_PROVIDER", "").casefold()
    if provider in {"anthropic", "claude"}:
        return AnthropicConfig.from_env()
    return OpenAICompatibleConfig.from_env()


def create_instrumented_client(config: ProviderConfig) -> InstrumentedLLMClient:
    """Create a client while preserving provider-specific API semantics."""

    if isinstance(config, AnthropicConfig):
        return AnthropicLLMClient(config)
    return OpenAICompatibleLLMClient(config)
