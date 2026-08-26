"""OpenAI adapter (official `openai` SDK), kept behind the same interface.

Deliberately uses `max_completion_tokens` (not the legacy `max_tokens`) and
sends no `temperature`, since recent reasoning models reject both.
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
    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.model = model or settings.openai_model
        # Empty string would shadow OPENAI_API_KEY; see the Anthropic adapter.
        self._client = openai.AsyncOpenAI(
            api_key=(api_key or settings.openai_api_key) or None
        )

    def _to_wire(self, system: str, messages: list[Message]) -> list[dict[str, Any]]:
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
        calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                # Never string-match serialized tool args - always parse.
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
