"""Provider selection. One place decides which SDK the agent talks to."""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm.base import LLMError, LLMProvider


@lru_cache
def get_llm_provider(name: str | None = None) -> LLMProvider:
    provider = (name or settings.llm_provider).lower()
    if provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if provider == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider()
    raise LLMError(f"Unknown LLM provider: {provider!r}")
