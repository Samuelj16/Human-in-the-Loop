"""Provider-neutral LLM interface.

The agent loop in `app/agent/loop.py` is written against these types only, so
swapping Claude for GPT is a config change rather than a rewrite. Anything a
provider needs that does not fit the neutral shape (Anthropic thinking blocks,
for example) rides along opaquely in `Message.provider_raw` and is only ever
read back by the provider that produced it.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Literal


class LLMError(RuntimeError):
    """Any provider failure the agent loop should surface rather than retry."""


class LLMRefusal(LLMError):
    """The model declined the request (Claude `stop_reason: "refusal"`)."""


class LLMTransientError(LLMError):
    """A failure worth retrying: rate limit, overload, 5xx, connection reset.

    A twelve-turn research run gets twelve chances to hit one of these, so
    treating them as fatal throws away most of a task's work.
    """


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    # Split out because cached input is billed at a tenth of fresh input;
    # folding them together would make cost reporting wrong.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )

    @property
    def billable_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Only set on role="tool"
    tool_call_id: str | None = None
    is_error: bool = False
    # Provider-specific echo payload (e.g. Anthropic content blocks incl.
    # thinking). Opaque to everyone except the provider that set it.
    provider_raw: Any = None


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    usage: Usage
    provider_raw: Any = None
    # Telemetry, persisted per turn so runs can be debugged and estimates tuned.
    latency_ms: int = 0
    attempts: int = 1
    model: str = ""

    def as_message(self) -> Message:
        return Message(
            role="assistant",
            content=self.text,
            tool_calls=self.tool_calls,
            provider_raw=self.provider_raw,
        )


def user_message(text: str) -> Message:
    return Message(role="user", content=text)


def assistant_message(text: str) -> Message:
    return Message(role="assistant", content=text)


def tool_result_message(
    call: ToolCall, content: str, *, is_error: bool = False
) -> Message:
    return Message(
        role="tool",
        content=content,
        tool_call_id=call.id,
        is_error=is_error,
    )


class LLMProvider(abc.ABC):
    """Minimal surface the agent needs: one non-streaming turn with tools."""

    name: str
    model: str

    @abc.abstractmethod
    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8000,
        cache_prefix: bool = False,
    ) -> LLMResponse:
        """One turn. `cache_prefix` marks the stable system+tools prefix as
        cacheable - worth it whenever the same prefix is resent across turns."""

    @abc.abstractmethod
    async def complete_json(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, Any],
        max_tokens: int = 2000,
    ) -> tuple[dict[str, Any], LLMResponse]:
        """A turn constrained to `schema`, so no output parsing is needed."""


def extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort JSON recovery from a model response.

    Needed for backends without constrained decoding - many open-weight servers
    support `json_object` but not a full JSON schema, and some support neither,
    so the last resort is parsing what the model wrote.
    """
    import json
    import re

    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise LLMError("Model did not return usable JSON.")
