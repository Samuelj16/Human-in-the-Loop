"""Unit tests for the Gemini provider adapter."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.base import LLMError, LLMTransientError, Message, ToolCall, ToolSpec, user_message
from app.llm.gemini_provider import GeminiProvider
from app.llm.registry import get_llm_provider
from app.pricing import cost_usd, is_priced


def test_gemini_models_are_priced():
    assert is_priced("gemini-3.6-flash")
    assert is_priced("gemini-2.5-flash")
    assert is_priced("gemini-2.5-pro")
    assert cost_usd("gemini-3.6-flash", input_tokens=1_000_000) == 0.10
    assert cost_usd("gemini-3.6-flash", output_tokens=1_000_000) == 0.40


def test_registry_resolves_gemini():
    provider = get_llm_provider("gemini")
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"


def test_empty_api_key_does_not_shadow_sdk_credential_resolution():
    provider = GeminiProvider(api_key="")
    assert provider.model


@pytest.mark.asyncio
async def test_gemini_provider_complete(monkeypatch):
    provider = GeminiProvider(api_key="test-key", model="gemini-3.6-flash")

    mock_choice = MagicMock()
    mock_choice.message.content = "Research report content"
    mock_choice.message.tool_calls = None
    mock_choice.finish_reason = "stop"

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 120
    mock_usage.completion_tokens = 50
    mock_usage.prompt_tokens_details = MagicMock(cached_tokens=20)

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_create = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(provider._client.chat.completions, "create", mock_create)

    res = await provider.complete(
        system="You are an assistant",
        messages=[user_message("Hello")],
    )

    assert res.text == "Research report content"
    assert res.usage.input_tokens == 100
    assert res.usage.output_tokens == 50
    assert res.usage.cache_read_tokens == 20
    assert res.stop_reason == "stop"
    assert mock_create.called


@pytest.mark.asyncio
async def test_gemini_provider_complete_json(monkeypatch):
    provider = GeminiProvider(api_key="test-key", model="gemini-3.6-flash")

    mock_choice = MagicMock()
    mock_choice.message.content = '{"restated_question": "test", "plan": ["step 1"], "clarifying_questions": []}'
    mock_choice.finish_reason = "stop"

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 50
    mock_usage.completion_tokens = 25
    mock_usage.prompt_tokens_details = None

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_create = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(provider._client.chat.completions, "create", mock_create)

    data, res = await provider.complete_json(
        system="You are a planner",
        messages=[user_message("Plan this")],
        schema={"type": "object"},
    )

    assert data["restated_question"] == "test"
    assert data["plan"] == ["step 1"]
    assert res.usage.input_tokens == 50
    assert res.usage.output_tokens == 25



async def test_rate_limit_is_transient_not_fatal():
    """Regression: a 429 must be retryable.

    `RateLimitError` subclasses `OpenAIError`, so a broad `except OpenAIError`
    placed above the specific handlers silently made every rate limit fatal and
    left the specific clauses unreachable. A research run makes many calls in
    quick succession, so on a free tier this failed almost every task.
    """
    import httpx2 as httpx
    import openai
    import pytest

    from app.llm.base import LLMError, LLMTransientError
    from app.llm.gemini_provider import GeminiProvider

    provider = GeminiProvider(api_key="fake-key", model="gemini-3-flash-preview")

    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(429, request=request, headers={"retry-after": "31"})

    async def boom(**kwargs):
        raise openai.RateLimitError(
            "quota exceeded. Please retry in 31.0s", response=response, body=None
        )

    provider._client.chat.completions.create = boom

    with pytest.raises(LLMTransientError) as exc:
        await provider._create({})

    assert not isinstance(exc.value, LLMError) or isinstance(exc.value, LLMTransientError)
    assert exc.value.retry_after == 31.0
