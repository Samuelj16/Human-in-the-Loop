"""Provider-neutral LLM interface and data models.

The agent loop in `app/agent/loop.py` is written against these types only, so
swapping Claude for GPT is a config change rather than a rewrite. Anything a
provider needs that does not fit the neutral shape (Anthropic thinking blocks,
for example) rides along opaquely in `Message.provider_raw` and is only ever
read back by the provider that produced it.

Classes & Data Types:
  - Error Hierarchy: `LLMError`, `LLMRefusal`, `LLMTransientError`.
  - Tool Representations: `ToolSpec`, `ToolCall`.
  - Token Accounting: `Usage` tracking input, output, cache-read, and cache-write tokens.
  - Neutral Conversation Structure: `Message`, `LLMResponse`.
  - Abstract Adapter Base: `LLMProvider`.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Literal


class LLMError(RuntimeError):
    """Any provider failure the agent loop should surface rather than retry."""
    pass


class LLMRefusal(LLMError):
    """The model declined the request (Claude `stop_reason: "refusal"`)."""
    pass


class LLMTransientError(LLMError):
    """A failure worth retrying: rate limit, overload, 5xx, connection reset.

    A twelve-turn research run gets twelve chances to hit one of these, so
    treating them as fatal throws away most of a task's work.

    `retry_after` carries the server's own stated delay when it gives one, which
    is more accurate than any backoff curve we could guess at.
    """

    def __init__(self, *args: object, retry_after: float | None = None) -> None:
        super().__init__(*args)
        self.retry_after = retry_after
    pass


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model: name, description, and JSON Schema.

    Provider-neutral; each adapter translates this into its own wire format.
    """
    name: str                           # Unique function/tool name
    description: str                    # Explanatory description guide for model tool selection
    input_schema: dict[str, Any]        # JSON Schema defining expected input parameter properties


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation requested by the model.

    `id` must be echoed back on the matching result, or the conversation breaks.
    """
    id: str                             # Unique tool invocation identifier
    name: str                           # Name of the tool called
    arguments: dict[str, Any]           # Parsed argument dictionary


@dataclass(frozen=True)
class Usage:
    """Token accounting for a single call.

    Cached input is tracked separately because it bills at a fraction of fresh
    input - folding them together would make cost reporting silently wrong.
    """
    input_tokens: int = 0               # Fresh un-cached input prompt tokens
    output_tokens: int = 0              # Completion/output tokens generated
    cache_read_tokens: int = 0          # Tokens read from ephemeral prompt cache
    cache_write_tokens: int = 0         # Tokens written to ephemeral prompt cache

    def __add__(self, other: "Usage") -> "Usage":
        """Combine token usages across multiple turns."""
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )

    @property
    def billable_input(self) -> int:
        """Every input token that costs money, cached or not."""
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass
class Message:
    """One turn in a provider-neutral conversation.

    `provider_raw` carries anything that does not fit this shape (Anthropic
    thinking blocks, for instance) and is only ever read back by the adapter
    that produced it.
    """
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
    """One model reply, plus the telemetry we persist per turn."""
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
        """Convert this reply into a history entry for the next turn."""
        return Message(
            role="assistant",
            content=self.text,
            tool_calls=self.tool_calls,
            provider_raw=self.provider_raw,
        )


def user_message(text: str) -> Message:
    """Build a standard user turn.
    
    Args:
        text: Prompt text.
        
    Returns:
        Message: User message turn.
    """
    return Message(role="user", content=text)


def assistant_message(text: str) -> Message:
    """Build an assistant turn with no tool calls.
    
    Args:
        text: Assistant completion text.
        
    Returns:
        Message: Assistant message turn.
    """
    return Message(role="assistant", content=text)


def tool_result_message(
    call: ToolCall, content: str, *, is_error: bool = False
) -> Message:
    """Build the result turn for a tool call.

    `is_error` tells the model the tool failed, which lets it recover instead of
    treating the error text as data.
    
    Args:
        call: The tool call being answered.
        content: Stringified result or error message.
        is_error: Whether the tool execution resulted in an error.
        
    Returns:
        Message: Tool result message turn.
    """
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
        """Execute one conversational turn.
        
        Args:
            system: System prompt instructions.
            messages: Neutral message history list.
            tools: Optional tool schemas available to model.
            max_tokens: Maximum tokens permitted in completion.
            cache_prefix: If True, marks system & tool prefix as cacheable.
            
        Returns:
            LLMResponse: Provider response and telemetry.
        """

    @abc.abstractmethod
    async def complete_json(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, Any],
        max_tokens: int = 2000,
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Execute a turn constrained strictly to a JSON schema.
        
        Args:
            system: System prompt instructions.
            messages: Neutral message history list.
            schema: JSON Schema definition.
            max_tokens: Maximum tokens permitted in completion.
            
        Returns:
            tuple[dict[str, Any], LLMResponse]: Parsed JSON data and the raw turn response.
        """


def extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort JSON recovery from a model response.

    Needed for backends without constrained decoding - many open-weight servers
    support `json_object` but not a full JSON schema, and some support neither,
    so the last resort is parsing what the model wrote.
    
    Args:
        text: Raw text string from model output.
        
    Returns:
        dict[str, Any]: Parsed JSON object.
        
    Raises:
        LLMError: If no valid JSON dictionary can be extracted.
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

