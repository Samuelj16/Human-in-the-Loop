"""Claude adapter (official `anthropic` SDK).

Notes that matter on current Claude models:
  * `thinking: {"type": "adaptive"}` - `budget_tokens` is rejected with a 400.
  * `temperature`/`top_p` are removed on Opus 5 / Sonnet 5; never send them.
  * `stop_reason` can be "refusal" on a 200 response - check it before reading
    content, and let server-side fallbacks reroute when the org has the beta.
  * Thinking blocks must be echoed back unchanged across tool-use turns, which
    is why the raw content list rides along in `Message.provider_raw`.
  * The system prompt + tool schemas are byte-identical across every turn of a
    research run, so they carry a cache breakpoint.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import anthropic

from app.config import settings
from app.llm.base import (
    LLMError,
    LLMProvider,
    LLMRefusal,
    LLMResponse,
    LLMTransientError,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from app.llm.retry import with_retry

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Anthropic will not cache a prefix below ~1024 tokens; a short system prompt
# plus tool schemas can fall under it, in which case this is a silent no-op.
CACHE_CONTROL = {"type": "ephemeral"}


class AnthropicProvider(LLMProvider):
    """Claude, via the official `anthropic` SDK.

    The fiddly parts are documented at the module level: adaptive thinking, no
    sampling parameters, refusal as a 200 response, and echoing thinking blocks
    back across tool turns.
    """
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        """Initialize the Anthropic client.
        
        Args:
            api_key: Optional explicit API key override.
            model: Optional model name override. Defaults to settings.anthropic_model.
        """
        self.model = model or settings.anthropic_model
        # An empty string must become None, or it overrides the SDK's own
        # credential resolution (env var, `ant auth login` profile) and the
        # client raises a bare TypeError at request time instead.
        raw_key = (api_key or settings.anthropic_api_key) or None
        if raw_key and (raw_key.startswith("AQ.") or raw_key.startswith("ey")):
            self._client = anthropic.AsyncAnthropic(auth_token=raw_key)
        elif raw_key:
            self._client = anthropic.AsyncAnthropic(api_key=raw_key)
        else:
            self._client = anthropic.AsyncAnthropic()
        self._use_fallbacks = settings.anthropic_enable_fallbacks

    # -- wire format -------------------------------------------------------
    def _to_wire(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Neutral messages -> Anthropic messages wire format.

        Consecutive tool results must be collapsed into a *single* user message;
        splitting them trains the model out of parallel tool calls.
        
        Args:
            messages: List of neutral Message instances.
            
        Returns:
            list[dict[str, Any]]: Anthropic API messages payload.
        """
        wire: list[dict[str, Any]] = []
        pending_results: list[dict[str, Any]] = []

        def flush_results() -> None:
            """Emit buffered tool results as one user message.

            Splitting them across messages trains the model out of parallel tool calls.
            """
            if pending_results:
                wire.append({"role": "user", "content": list(pending_results)})
                pending_results.clear()

        for msg in messages:
            if msg.role == "tool":
                pending_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                        **({"is_error": True} if msg.is_error else {}),
                    }
                )
                continue

            flush_results()

            if msg.role == "user":
                wire.append({"role": "user", "content": msg.content})
            elif msg.provider_raw is not None:
                # Replay Claude's own blocks verbatim (keeps thinking intact).
                wire.append({"role": "assistant", "content": msg.provider_raw})
            else:
                blocks: list[dict[str, Any]] = []
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                for call in msg.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                wire.append({"role": "assistant", "content": blocks or msg.content})

        flush_results()
        return wire

    @staticmethod
    def _tools_to_wire(tools: list[ToolSpec] | None) -> list[dict[str, Any]]:
        """Translate neutral ToolSpecs to Anthropic tools array."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in (tools or [])
        ]

    @staticmethod
    def _system_to_wire(system: str, cache_prefix: bool) -> Any:
        """Format system prompt with optional ephemeral cache control."""
        if not cache_prefix:
            return system
        # Render order is tools -> system -> messages, so a breakpoint at the
        # end of `system` caches the tool schemas too.
        return [{"type": "text", "text": system, "cache_control": CACHE_CONTROL}]

    @staticmethod
    def _usage(response: Any) -> Usage:
        """Extract token usage and cache metrics from Anthropic response object."""
        usage = response.usage
        return Usage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )

    def _check_refusal(self, response: Any) -> None:
        """Check for model refusal and raise LLMRefusal if request was rejected."""
        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            raise LLMRefusal(
                "Claude declined this request "
                f"({getattr(detail, 'category', 'unknown')})."
            )

    # -- requests ----------------------------------------------------------
    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8000,
        cache_prefix: bool = False,
    ) -> LLMResponse:
        """One research turn, with tools and a cacheable prefix."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": self._system_to_wire(system, cache_prefix),
            "messages": self._to_wire(messages),
            "thinking": {"type": "adaptive"},
        }
        wire_tools = self._tools_to_wire(tools)
        if wire_tools:
            kwargs["tools"] = wire_tools

        started = time.perf_counter()
        response, attempts = await with_retry(
            lambda: self._create(kwargs), label=f"anthropic {self.model}"
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        self._check_refusal(response)

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )

        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            stop_reason=response.stop_reason or "end_turn",
            usage=self._usage(response),
            # Echoed back verbatim on the next turn so thinking blocks survive.
            provider_raw=response.content,
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
        """Constrained output - the API guarantees schema-valid JSON."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": self._to_wire(messages),
            "thinking": {"type": "adaptive"},
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }

        started = time.perf_counter()
        response, attempts = await with_retry(
            lambda: self._create(kwargs), label=f"anthropic {self.model} (json)"
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        self._check_refusal(response)

        text = next(
            (b.text for b in response.content if b.type == "text"), ""
        ).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Constrained output was not valid JSON: {text[:200]}") from exc

        return data, LLMResponse(
            text=text,
            tool_calls=[],
            stop_reason=response.stop_reason or "end_turn",
            usage=self._usage(response),
            latency_ms=latency_ms,
            attempts=attempts,
            model=self.model,
        )

    async def _create(self, kwargs: dict[str, Any]):
        """Send the request, mapping SDK errors onto retryable/fatal."""
        try:
            if self._use_fallbacks:
                return await self._client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs
                )
            return await self._client.messages.create(**kwargs)
        except anthropic.BadRequestError as exc:
            if self._use_fallbacks:
                # Most likely the account is not enrolled in the fallback beta.
                log.warning(
                    "Disabling Anthropic server-side fallbacks after 400: %s", exc
                )
                self._use_fallbacks = False
                return await self._client.messages.create(**kwargs)
            raise LLMError(f"Anthropic rejected the request: {exc}") from exc
        except anthropic.AuthenticationError as exc:
            raise LLMError("ANTHROPIC_API_KEY is missing or invalid.") from exc
        except TypeError as exc:
            # The SDK raises a plain TypeError when no credential source at all
            # resolves. Left unmapped it escapes every `except LLMError` in the
            # job layer and wedges the task.
            raise LLMError(
                "No Anthropic credentials found. Set ANTHROPIC_API_KEY "
                f"(or run `ant auth login`). Underlying error: {exc}"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LLMTransientError(f"Anthropic rate limit: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMTransientError(f"Could not reach the Anthropic API: {exc}") from exc
        except anthropic.APIStatusError as exc:
            # 529 = overloaded, 5xx = server side. Both are worth another go.
            if exc.status_code >= 500:
                raise LLMTransientError(
                    f"Anthropic server error {exc.status_code}: {exc}"
                ) from exc
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc}") from exc

