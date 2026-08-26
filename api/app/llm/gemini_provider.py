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
import re
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


def _retry_after_from(exc: Exception) -> float | None:
    """Pull the server's own retry delay out of a 429.

    Gemini reports a precise delay ("Please retry in 31.08s"); honouring it
    beats guessing, because free-tier quotas reset on a fixed window that our
    exponential backoff would otherwise undershoot.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers:
        raw = headers.get("retry-after")
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass

    match = re.search(r"retry in ([\d.]+)s", str(exc))
    if match:
        return float(match.group(1))
    match = re.search(r"'retryDelay': '(\d+)s'", str(exc))
    if match:
        return float(match.group(1))
    return None


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
                if msg.provider_raw is not None:
                    # Gemini 3 requires the `thought_signature` it attached to a
                    # function call to come back unchanged on the next turn;
                    # without it the API rejects the request with a 400. That
                    # signature lives in a non-standard `extra_content` field, so
                    # rebuilding the message from our neutral types would drop it.
                    # Replaying Gemini's own message verbatim keeps it intact -
                    # the same reason the Anthropic adapter replays its thinking
                    # blocks rather than reconstructing them.
                    wire.append(msg.provider_raw)
                    continue

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
            # Kept so the next turn can echo this message back exactly, including
            # the thought_signature Gemini requires on function calls.
            provider_raw=choice.message.model_dump(exclude_none=True),
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
        # Order matters: RateLimitError, APIConnectionError and APIStatusError
        # are all subclasses of OpenAIError, so a broad `except OpenAIError`
        # placed first would swallow them and make every rate limit fatal.
        except openai.AuthenticationError as exc:
            raise LLMError("GEMINI_API_KEY is missing or invalid.") from exc
        except openai.RateLimitError as exc:
            raise LLMTransientError(
                f"Gemini rate limit: {exc}", retry_after=_retry_after_from(exc)
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMTransientError(f"Could not reach the Gemini API: {exc}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMTransientError(
                    f"Gemini server error {exc.status_code}: {exc}"
                ) from exc
            raise LLMError(f"Gemini API error {exc.status_code}: {exc}") from exc
        except (TypeError, openai.OpenAIError) as exc:
            raise LLMError(f"Gemini client is not configured: {exc}") from exc


