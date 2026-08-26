"""Open-weight models behind an OpenAI-compatible endpoint.

Two layers:
  * a real HTTP round trip against a stub server, so the base-URL plumbing and
    the SDK wire format are genuinely exercised;
  * monkeypatched capability failures, to drive the degradation chain that a
    modest local server actually triggers.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.llm.base import LLMError, user_message
from app.llm.openai_compatible import PRESETS, OpenAICompatibleProvider

SCHEMA = {
    "type": "object",
    "properties": {"plan": {"type": "array", "items": {"type": "string"}}},
    "required": ["plan"],
    "additionalProperties": False,
}


def _completion(content: str, tool_calls=None) -> dict:
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "created": 0,
        "model": "stub-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


class _StubServer:
    """A minimal OpenAI-compatible server, like a local runtime would be."""

    def __init__(self, *, reject: set[str] | None = None, content='{"plan": ["a"]}'):
        self.reject = reject or set()
        self.content = content
        self.requests: list[dict] = []

        handler = self._make_handler()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep pytest output clean
                pass

            def do_POST(self):
                length = int(self.headers.get("content-length", 0))
                body = json.loads(self.rfile.read(length) or "{}")
                server.requests.append(body)

                fmt = (body.get("response_format") or {}).get("type")
                if fmt and fmt in server.reject:
                    return self._send(400, {"error": {"message": f"{fmt} not supported"}})
                if "max_completion_tokens" in body and "max_completion_tokens" in server.reject:
                    return self._send(
                        400,
                        {"error": {"message": "Unrecognized request argument: max_completion_tokens"}},
                    )

                self._send(200, _completion(server.content))

            def _send(self, code: int, payload: dict):
                raw = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return Handler

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def stub():
    servers: list[_StubServer] = []

    def make(**kwargs):
        s = _StubServer(**kwargs)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def _provider(server, **kwargs) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        preset="ollama", base_url=server.base_url, model="llama3.1:8b", **kwargs
    )


# -- configuration ----------------------------------------------------------
def test_known_presets_resolve_without_a_base_url():
    provider = OpenAICompatibleProvider(preset="ollama", model="llama3.1:8b")
    assert provider.base_url == PRESETS["ollama"]
    assert provider.is_local


def test_hosted_endpoint_without_a_key_fails_with_an_actionable_message():
    """A missing credential must not surface as a raw SDK error mid-job."""
    with pytest.raises(LLMError) as exc:
        OpenAICompatibleProvider(preset="openrouter", model="some/model")
    assert "OPEN_MODEL_API_KEY" in str(exc.value)


def test_local_endpoint_needs_no_key():
    provider = OpenAICompatibleProvider(preset="ollama", model="llama3.1:8b")
    assert provider.is_local


def test_unknown_endpoint_without_a_base_url_is_rejected():
    with pytest.raises(LLMError) as exc:
        OpenAICompatibleProvider(preset="nope", model="m")
    assert "base URL" in str(exc.value)


# -- real HTTP round trip ---------------------------------------------------
async def test_completion_over_real_http(stub):
    server = stub(content="Hello from an open model.")
    provider = _provider(server)

    response = await provider.complete(system="sys", messages=[user_message("hi")])

    assert response.text == "Hello from an open model."
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 7
    assert response.model == "llama3.1:8b"
    sent = server.requests[0]
    assert sent["model"] == "llama3.1:8b"
    assert sent["messages"][0] == {"role": "system", "content": "sys"}


async def test_structured_output_uses_json_schema_when_supported(stub):
    server = stub()
    provider = _provider(server)

    data, _ = await provider.complete_json(
        system="sys", messages=[user_message("q")], schema=SCHEMA
    )

    assert data == {"plan": ["a"]}
    assert server.requests[0]["response_format"]["type"] == "json_schema"


async def test_falls_back_to_json_object_when_schema_is_unsupported(stub):
    """Most local runtimes implement json_object but not strict json_schema."""
    server = stub(reject={"json_schema"})
    provider = _provider(server)

    data, _ = await provider.complete_json(
        system="sys", messages=[user_message("q")], schema=SCHEMA
    )

    assert data == {"plan": ["a"]}
    assert [r["response_format"]["type"] for r in server.requests] == [
        "json_schema",
        "json_object",
    ]


async def test_falls_back_to_prompted_json_when_neither_is_supported(stub):
    server = stub(reject={"json_schema", "json_object"}, content='```json\n{"plan": ["b"]}\n```')
    provider = _provider(server)

    data, _ = await provider.complete_json(
        system="sys", messages=[user_message("q")], schema=SCHEMA
    )

    # Fenced output from a chattier model is still recovered.
    assert data == {"plan": ["b"]}
    last = server.requests[-1]
    assert "response_format" not in last
    # The schema has to reach the model somehow when the server cannot enforce it.
    assert "Schema:" in last["messages"][0]["content"]


async def test_capability_probe_latches(stub):
    """The unsupported mode is tried once per process, not once per call."""
    server = stub(reject={"json_schema"})
    provider = _provider(server)

    for _ in range(3):
        await provider.complete_json(
            system="s", messages=[user_message("q")], schema=SCHEMA
        )

    schema_attempts = [
        r for r in server.requests
        if (r.get("response_format") or {}).get("type") == "json_schema"
    ]
    assert len(schema_attempts) == 1, "should stop retrying a known-unsupported mode"


async def test_falls_back_to_legacy_token_limit_parameter(stub):
    server = stub(reject={"max_completion_tokens"}, content="ok")
    provider = _provider(server)

    await provider.complete(system="s", messages=[user_message("q")], max_tokens=123)

    assert "max_completion_tokens" in server.requests[0]
    assert server.requests[-1]["max_tokens"] == 123


async def test_unparseable_json_raises_rather_than_returning_garbage(stub):
    server = stub(reject={"json_schema", "json_object"}, content="I can't do that, sorry.")
    provider = _provider(server)

    with pytest.raises(LLMError):
        await provider.complete_json(
            system="s", messages=[user_message("q")], schema=SCHEMA
        )


# -- cost -------------------------------------------------------------------
def test_a_model_on_your_own_hardware_costs_nothing(monkeypatch):
    """The approval gate must say $0.00, not fall back to a guessed price."""
    from app.pricing import estimate_task_cost, is_priced

    monkeypatch.setattr("app.config.settings.open_model_name", "llama3.1:8b")
    monkeypatch.setattr("app.config.settings.open_model_price_input", 0.0)
    monkeypatch.setattr("app.config.settings.open_model_price_output", 0.0)

    assert is_priced("llama3.1:8b"), "a configured local model is priced, not guessed"
    estimate = estimate_task_cost(
        ["a", "b"], model="llama3.1:8b", max_searches=8, max_iterations=12
    )
    assert estimate.expected_usd == 0.0
    assert estimate.priced is True


def test_hosted_open_model_prices_come_from_config(monkeypatch):
    from app.pricing import cost_usd

    monkeypatch.setattr("app.config.settings.open_model_name", "meta-llama/llama-3.3-70b")
    monkeypatch.setattr("app.config.settings.open_model_price_input", 0.60)
    monkeypatch.setattr("app.config.settings.open_model_price_output", 0.60)

    assert cost_usd("meta-llama/llama-3.3-70b", input_tokens=1_000_000) == 0.60
