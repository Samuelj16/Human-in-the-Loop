"""OpenAI adapter (official `openai` SDK), kept behind the same interface.

Deliberately uses `max_completion_tokens` (not the legacy `max_tokens`) and
sends no `temperature`, since recent reasoning models reject both.

Design Notes:
  - Base Class for OpenAI-Compatible Endpoints: Inherited by `OpenAICompatibleProvider`.
  - Token Accounting Reconciliation: OpenAI's `prompt_tokens` includes cached tokens,
    whereas Anthropic separates them. This adapter subtracts cached tokens from input_tokens
    so both providers report normalized, comparable metrics.
  - Automatic Prompt Caching: OpenAI automatically caches stable prefixes without needing
    explicit breakpoint markers.
"""
from __future__ import annotations

import json
import time
from typing import Any

import openai

from app.config import settings
from app.llm.base import (
    LLMError,
    LLMProvider,
    LLMResponse,
    LLMTransientError,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from app.llm.retry import with_retry


class OpenAIProvider(LLMProvider):
    """OpenAI, via the official `openai` SDK.

    Also the base class for any OpenAI-compatible endpoint - see
    openai_compatible.py for open-weight backends and gemini_provider.py.
    """
    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        """Initialize the OpenAI client.
        
        Args:
            api_key: Optional explicit API key override. Defaults to settings.openai_api_key.
            model: Optional model override. Defaults to settings.openai_model.
        """
        self.model = model or settings.openai_model
        # Empty string would shadow OPENAI_API_KEY; see the Anthropic adapter.
        self._client = openai.AsyncOpenAI(
            api_key=(api_key or settings.openai_api_key) or None
        )

    def _to_wire(self, system: str, messages: list[Message]) -> list[dict[str, Any]]:
        """Translate neutral Message list to OpenAI chat completion message format."""
        wire: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for msg in messages:
            if msg.role == "user":
                wire.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or None,
                }
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": json.dumps(c.arguments),
                            },
                        }
                        for c in msg.tool_calls
                    ]
                wire.append(entry)
            else:  # tool result
                wire.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )
        return wire

    @staticmethod
    def _tools_to_wire(tools: list[ToolSpec] | None) -> list[dict[str, Any]]:
        """Translate neutral ToolSpecs to OpenAI functions schema definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in (tools or [])
        ]

    @staticmethod
    def _calls_from(choice: Any) -> list[ToolCall]:
        """Parse tool calls off a chat-completion choice.

        Shared with the open-model adapter, which speaks the same wire format.
        """
        return [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                # Never string-match serialized tool args - always parse.
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.message.tool_calls or [])
            if getattr(tc, "function", None) is not None
        ]

    @staticmethod
    def _usage(response: Any) -> Usage:
        """Extract and normalize token usage from OpenAI response object."""
        usage = response.usage
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        return Usage(
            # OpenAI's prompt_tokens *includes* cached tokens; Anthropic's does
            # not. Subtract so the two providers report the same thing.
            input_tokens=max(0, prompt - cached),
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cache_read_tokens=cached,
        )

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8000,
        cache_prefix: bool = False,
    ) -> LLMResponse:
        # `cache_prefix` is a no-op here: OpenAI caches long stable prefixes
        # automatically, with no breakpoint to declare.
        """One research turn, with tools."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_wire(system, messages),
            "max_completion_tokens": max_tokens,
        }
        wire_tools = self._tools_to_wire(tools)
        if wire_tools:
            kwargs["tools"] = wire_tools

        started = time.perf_counter()
        response, attempts = await with_retry(
            lambda: self._create(kwargs), label=f"openai {self.model}"
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        choice = response.choices[0]
        calls = self._calls_from(choice)
        return LLMResponse(
            text=(choice.message.content or "").strip(),
            tool_calls=calls,
            stop_reason="tool_use" if calls else (choice.finish_reason or "end_turn"),
            usage=self._usage(response),
            latency_ms=latency_ms,
            attempts=attempts,
            model=self.model,
        )

    async def complete_json(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, Any],
        max_tokens: int = 2000,
    ) -> tuple[dict[str, Any], LLMResponse]:
        """One turn constrained to a JSON schema, so no output parsing is needed."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_wire(system, messages),
            "max_completion_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "schema": schema,
                    "strict": True,
                },
            },
        }

        started = time.perf_counter()
        response, attempts = await with_retry(
            lambda: self._create(kwargs), label=f"openai {self.model} (json)"
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        text = (response.choices[0].message.content or "").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Constrained output was not valid JSON: {text[:200]}") from exc

        return data, LLMResponse(
            text=text,
            tool_calls=[],
            stop_reason=response.choices[0].finish_reason or "end_turn",
            usage=self._usage(response),
            latency_ms=latency_ms,
            attempts=attempts,
            model=self.model,
        )

    async def _create(self, kwargs: dict[str, Any]):
        """Send chat completion request to OpenAI API with mapped error classifications."""
        try:
            return await self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise LLMError("OPENAI_API_KEY is missing or invalid.") from exc
        except (TypeError, openai.OpenAIError) as exc:
            raise LLMError(f"OpenAI client is not configured: {exc}") from exc
        except openai.RateLimitError as exc:
            raise LLMTransientError(f"OpenAI rate limit: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise LLMTransientError(f"Could not reach the OpenAI API: {exc}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMTransientError(
                    f"OpenAI server error {exc.status_code}: {exc}"
                ) from exc
            raise LLMError(f"OpenAI API error {exc.status_code}: {exc}") from exc

