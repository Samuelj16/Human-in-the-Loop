"""Provider selection. One place decides which SDK the agent talks to."""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm.base import LLMError, LLMProvider


@lru_cache
def get_llm_provider(name: str | None = None) -> LLMProvider:
    """Build the configured provider.

    The single place that decides which SDK the agent talks to. Cached, because
    adapters are stateless apart from their client and capability probes.
    """
    provider = (name or settings.llm_provider).lower()
    if provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if provider == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider()
    if provider == "gemini":
        from app.llm.gemini_provider import GeminiProvider

        return GeminiProvider()
    # Everything else is an OpenAI-compatible endpoint serving open weights.
    from app.llm.openai_compatible import PRESETS, OpenAICompatibleProvider

    if provider in PRESETS or provider == "open":
        return OpenAICompatibleProvider(
            preset=None if provider == "open" else provider
        )

    raise LLMError(
        f"Unknown LLM provider: {provider!r}. Expected anthropic, openai, "
        f"gemini, open, or one of: {', '.join(sorted(PRESETS))}."
    )
