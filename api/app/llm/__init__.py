"""Public LLM interface and provider registry.

Exports the core types and factory used by the agent execution loop:
  - `LLMProvider`: Abstract base class for model adapters.
  - `LLMResponse`: Result object carrying text, tool calls, and telemetry.
  - `LLMError`, `LLMRefusal`, `LLMTransientError`: Error taxonomy.
  - `Message`, `ToolCall`, `ToolSpec`, `Usage`: Conversation building blocks.
  - `get_llm_provider`: Provider factory resolving settings.llm_provider.
"""

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
    assistant_message,
    tool_result_message,
    user_message,
)
from app.llm.registry import get_llm_provider

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMRefusal",
    "LLMResponse",
    "LLMTransientError",
    "Message",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "assistant_message",
    "get_llm_provider",
    "tool_result_message",
    "user_message",
]
