"""Gemini adapter (via Google AI Studio OpenAI-compatible endpoint).

Uses the official OpenAI SDK pointing to Google's Generative Language API endpoint:
https://generativelanguage.googleapis.com/v1beta/openai/

Features:
  - Connects to Google AI Studio with OpenAI SDK syntax.
  - Implements chat completions wire format with tool call parsing.
  - Supports strict schema-constrained JSON output for planning.
  - Automatically isolates cached tokens from prompt tokens for accurate billing telemetry.
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


class GeminiProvider(LLMProvider):
    """Gemini, via Google's OpenAI-compatible endpoint.

    Note the wire-format methods below duplicate OpenAIProvider almost exactly,
    since both speak /v1/chat/completions. They are worth collapsing into the
    shared base class next time this file is touched.
    """
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        """Initialize the Gemini client using Google's OpenAI-compatible endpoint.
        
        Args:
            api_key: Optional explicit API key override. Defaults to settings.gemini_api_key.
            model: Optional model override. Defaults to settings.gemini_model.
        """
        self.model = model or settings.gemini_model
        resolved_key = (api_key or settings.gemini_api_key) or None
        self._client = openai.AsyncOpenAI(
            api_key=resolved_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    def _to_wire(self, system: str, messages: list[Message]) -> list[dict[str, Any]]:
        """Translate neutral messages to OpenAI-compatible wire messages."""
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
        """Translate ToolSpec list to OpenAI-style tool schema definitions."""
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
    def _usage(response: Any) -> Usage:
        """Extract token usage metrics and cache reads from response payload."""
        usage = getattr(response, "usage", None)
        if not usage:
            return Usage()
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        return Usage(
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
        """One research turn, with tools."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_wire(system, messages),
            "max_tokens": max_tokens,
        }
        wire_tools = self._tools_to_wire(tools)
        if wire_tools:
            kwargs["tools"] = wire_tools

        started = time.perf_counter()
        response, attempts = await with_retry(
            lambda: self._create(kwargs), label=f"gemini {self.model}"
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        choice = response.choices[0]
        calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.message.tool_calls or [])
            if getattr(tc, "function", None) is not None
        ]
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
        """One turn constrained to a JSON schema."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_wire(system, messages),
            "max_tokens": max_tokens,
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
            lambda: self._create(kwargs), label=f"gemini {self.model} (json)"
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
        """Send chat completion request with mapped error handling."""
        try:
            return await self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise LLMError("GEMINI_API_KEY is missing or invalid.") from exc
        except (TypeError, openai.OpenAIError) as exc:
            raise LLMError(f"Gemini client is not configured: {exc}") from exc
        except openai.RateLimitError as exc:
            raise LLMTransientError(f"Gemini rate limit: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise LLMTransientError(f"Could not reach the Gemini API: {exc}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMTransientError(
                    f"Gemini server error {exc.status_code}: {exc}"
                ) from exc
            raise LLMError(f"Gemini API error {exc.status_code}: {exc}") from exc


