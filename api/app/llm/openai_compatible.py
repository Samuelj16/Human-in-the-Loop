"""Open-weight models behind an OpenAI-compatible endpoint.

Nearly every way of serving open models - Ollama and llama.cpp locally, vLLM on
your own box, OpenRouter / Groq / Together / Fireworks in the cloud - exposes the
same `/v1/chat/completions` shape. So this is one adapter with a configurable
base URL rather than one adapter per vendor.

What differs between them is not the request shape but which *optional* features
the server implements. A hosted frontier API supports strict JSON schemas and
`max_completion_tokens`; a local Ollama build may support neither. Rather than
demanding a lowest common denominator, this adapter probes and degrades:

    json_schema  ->  json_object  ->  parse what the model wrote
    max_completion_tokens  ->  max_tokens

Each fallback latches after the first rejection, so the cost is one wasted
request per process, not one per call.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import openai

from app.config import settings
from app.llm.base import (
    LLMError,
    LLMResponse,
    Message,
    ToolSpec,
    extract_json_object,
)
from app.llm.openai_provider import OpenAIProvider
from app.llm.retry import with_retry

log = logging.getLogger(__name__)

# Short names so LLM_PROVIDER=ollama just works without a base URL.
PRESETS: dict[str, str] = {
    "ollama": "http://localhost:11434/v1",
    "llamacpp": "http://localhost:8080/v1",
    "lmstudio": "http://localhost:1234/v1",
    "vllm": "http://localhost:8000/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
}

# Backends that run on your own hardware: no per-token bill, so the approval
# gate should say $0.00 rather than guess at a price.
LOCAL_PRESETS = {"ollama", "llamacpp", "lmstudio", "vllm"}

JSON_INSTRUCTION = (
    "Respond with a single JSON object matching this schema. Output only the "
    "JSON - no prose, no code fences.\n\nSchema:\n{schema}"
)


class OpenAICompatibleProvider(OpenAIProvider):
    """Any OpenAI-compatible server, including local open-weight models."""

    def __init__(
        self,
        preset: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize open-model adapter with preset or custom base URL.
        
        Args:
            preset: Provider preset name (ollama, groq, openrouter, etc.).
            base_url: Custom base URL override.
            api_key: API key override.
            model: Model identifier override.
        """
        self.preset = (preset or settings.open_model_preset or "").lower()
        self.name = self.preset or "open-model"
        self.base_url = (
            base_url or settings.open_model_base_url or PRESETS.get(self.preset) or ""
        )
        if not self.base_url:
            raise LLMError(
                f"No base URL for open-model provider {self.preset!r}. Set "
                "OPEN_MODEL_BASE_URL, or use a known preset: "
                f"{', '.join(sorted(PRESETS))}."
            )

        self.model = model or settings.open_model_name
        if not self.model:
            raise LLMError(
                "OPEN_MODEL_NAME is not set - e.g. 'llama3.1:8b' for Ollama, or "
                "'meta-llama/llama-3.3-70b-instruct' for OpenRouter."
            )

        # Local servers ignore the key, but the SDK insists on a non-empty one.
        key = (api_key or settings.open_model_api_key) or None
        if key is None:
            if not self.is_local:
                # Same lesson as the Anthropic adapter: a missing credential must
                # produce an actionable message, not a raw SDK error from deep
                # inside a background job.
                raise LLMError(
                    f"{self.name} needs a key. Set OPEN_MODEL_API_KEY "
                    f"(get one from the {self.name} dashboard), or point "
                    "LLM_PROVIDER at a local runtime such as ollama."
                )
            key = "local-no-key-needed"

        self._client = openai.AsyncOpenAI(base_url=self.base_url, api_key=key)

        # Capability probes, latched after the first rejection.
        self._supports_json_schema = True
        self._supports_json_object = True
        self._supports_max_completion_tokens = True

    @property
    def is_local(self) -> bool:
        """True when the model runs on this machine, and so costs nothing per token."""
        return self.preset in LOCAL_PRESETS or "localhost" in self.base_url or (
            "127.0.0.1" in self.base_url
        )

    # -- token-limit parameter naming --------------------------------------
    def _token_limit_kwargs(self, max_tokens: int) -> dict[str, Any]:
        """Choose between max_completion_tokens and max_tokens depending on probed support."""
        if self._supports_max_completion_tokens:
            return {"max_completion_tokens": max_tokens}
        return {"max_tokens": max_tokens}

    async def _create(self, kwargs: dict[str, Any]):
        """Send request to backend, falling back to max_tokens if max_completion_tokens is rejected."""
        try:
            return await super()._create(kwargs)
        except LLMError as exc:
            message = str(exc).lower()
            if (
                self._supports_max_completion_tokens
                and "max_completion_tokens" in kwargs
                and ("max_completion_tokens" in message or "unrecognized" in message)
            ):
                # Older/simpler servers only know the legacy parameter name.
                log.info("%s rejects max_completion_tokens; using max_tokens", self.name)
                self._supports_max_completion_tokens = False
                kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
                return await super()._create(kwargs)
            raise

    # -- completion --------------------------------------------------------
    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8000,
        cache_prefix: bool = False,
    ) -> LLMResponse:
        """One turn, using whichever token-limit parameter this server accepts."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_wire(system, messages),
            **self._token_limit_kwargs(max_tokens),
        }
        wire_tools = self._tools_to_wire(tools)
        if wire_tools:
            kwargs["tools"] = wire_tools

        started = time.perf_counter()
        response, attempts = await with_retry(
            lambda: self._create(kwargs), label=f"{self.name} {self.model}"
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        return self._to_response(response, latency_ms, attempts)

    # -- constrained output, with graceful degradation ----------------------
    async def complete_json(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, Any],
        max_tokens: int = 2000,
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Structured output, degrading to whatever this server supports.

        Tries a strict JSON schema, then `json_object` with the schema in the prompt,
        then plain prompting with best-effort parsing. Each rejection latches, so an
        unsupported mode costs one wasted request per process, not one per call.
        """
        attempts_log: list[str] = []

        for mode in ("json_schema", "json_object", "prompt"):
            if mode == "json_schema" and not self._supports_json_schema:
                continue
            if mode == "json_object" and not self._supports_json_object:
                continue

            effective_system = system
            kwargs: dict[str, Any] = {
                "model": self.model,
                **self._token_limit_kwargs(max_tokens),
            }

            if mode == "json_schema":
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_output",
                        "schema": schema,
                        "strict": True,
                    },
                }
            elif mode == "json_object":
                kwargs["response_format"] = {"type": "json_object"}
                effective_system = (
                    f"{system}\n\n"
                    + JSON_INSTRUCTION.format(schema=json.dumps(schema, indent=2))
                )
            else:
                effective_system = (
                    f"{system}\n\n"
                    + JSON_INSTRUCTION.format(schema=json.dumps(schema, indent=2))
                )

            kwargs["messages"] = self._to_wire(effective_system, messages)

            started = time.perf_counter()
            try:
                response, attempts = await with_retry(
                    lambda: self._create(kwargs),
                    label=f"{self.name} {self.model} (json/{mode})",
                )
            except LLMError as exc:
                if mode == "prompt":
                    raise
                # This server does not implement this response_format; latch off.
                log.info("%s rejected %s: %s", self.name, mode, exc)
                attempts_log.append(f"{mode}: {exc}")
                if mode == "json_schema":
                    self._supports_json_schema = False
                else:
                    self._supports_json_object = False
                continue

            latency_ms = int((time.perf_counter() - started) * 1000)
            text = (response.choices[0].message.content or "").strip()

            try:
                data = extract_json_object(text) if mode != "json_schema" else json.loads(text)
            except (json.JSONDecodeError, LLMError) as exc:
                if mode == "prompt":
                    raise LLMError(
                        f"{self.model} did not return usable JSON: {text[:200]}"
                    ) from exc
                attempts_log.append(f"{mode}: unparseable output")
                continue

            return data, self._to_response(response, latency_ms, attempts)

        raise LLMError(
            f"{self.model} could not produce structured output. Tried: "
            + "; ".join(attempts_log)
        )

    def _to_response(self, response: Any, latency_ms: int, attempts: int) -> LLMResponse:
        """Construct neutral LLMResponse from OpenAI response object."""
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
