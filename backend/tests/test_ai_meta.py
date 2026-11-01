"""Spec 004: Meta Model API adapter with a fake transport (AC-AI-07 to AC-AI-11).

No test opens a network connection: every `MetaProvider` gets `FakeTransport`. The wire
format checked here is spec 004 assumptions A2, A3 and A5.
"""
from __future__ import annotations

import http.client
import json

import pytest

from dealpilot.ai import (
    AIAuthError,
    AIBillingError,
    AIError,
    AIProviderError,
    AIRateLimitError,
    AIResponseError,
    AITimeoutError,
    CompletionRequest,
    CompletionResult,
    Message,
    Usage,
    load_settings,
)
from dealpilot.ai.meta import MetaProvider, https_transport

FAKE_KEY = "fake-test-" + "k" * 16
LEAK_BODY = "server says: internal detail"


class FakeTransport:
    """Records each call and returns a fixed answer or raises a fixed exception."""

    def __init__(self, status: int = 200, body: bytes | str | dict = b"",
                 exc: BaseException | None = None) -> None:
        self.status = status
        self.body = (json.dumps(body).encode() if isinstance(body, dict)
                     else body.encode() if isinstance(body, str) else body)
        self.exc = exc
        self.calls: list[tuple] = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body, timeout))
        if self.exc is not None:
            raise self.exc
        return self.status, self.body


def _provider(transport: FakeTransport, **env: str) -> MetaProvider:
    settings = load_settings({"DEALPILOT_AI_PROVIDER": "meta",
                              "DEALPILOT_META_API_KEY": FAKE_KEY, **env})
    return MetaProvider(settings, transport=transport)


def _request() -> CompletionRequest:
    return CompletionRequest([Message("system", "Be brief."), Message("user", "Top region?")],
                             max_tokens=64, temperature=0.2)


OK_BODY = {
    "model": "muse-spark-1.3",
    "choices": [{"message": {"role": "assistant", "content": "North."},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 2},
}


def test_ac_ai_07_request_shape() -> None:
    transport = FakeTransport(body=OK_BODY)
    _provider(transport, DEALPILOT_AI_TIMEOUT_SECONDS="12",
              DEALPILOT_META_BASE_URL="https://example.test/v1/").complete(_request())
    assert len(transport.calls) == 1
    method, url, headers, body, timeout = transport.calls[0]
    assert (method, url, timeout) == ("POST", "https://example.test/v1/chat/completions", 12.0)
    assert headers["Authorization"] == "Bearer " + FAKE_KEY
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {
        "model": "muse-spark-1.3",
        "messages": [{"role": "system", "content": "Be brief."},
                     {"role": "user", "content": "Top region?"}],
        "max_tokens": 64,
        "temperature": 0.2,
    }


def test_ac_ai_07_default_url_and_timeout() -> None:
    transport = FakeTransport(body=OK_BODY)
    _provider(transport).complete(_request())
    assert transport.calls[0][1] == "https://api.meta.ai/v1/chat/completions"
    assert transport.calls[0][4] == 30.0


def test_ac_ai_07_no_call_before_complete() -> None:
    transport = FakeTransport(body=OK_BODY)
    _provider(transport)
    assert transport.calls == []


def test_ac_ai_08_valid_response() -> None:
    result = _provider(FakeTransport(body=OK_BODY)).complete(_request())
    assert result == CompletionResult(text="North.", provider="meta", model="muse-spark-1.3",
                                      finish_reason="stop", usage=Usage(12, 2))


def test_ac_ai_08_optional_fields_missing() -> None:
    body = {"choices": [{"message": {"content": ""}}]}
    result = _provider(FakeTransport(body=body)).complete(_request())
    assert result == CompletionResult(text="", provider="meta", model="muse-spark-1.3",
                                      finish_reason=None, usage=None)


@pytest.mark.parametrize(("status", "error"), [
    (401, AIAuthError),
    (403, AIAuthError),
    (402, AIBillingError),
    (429, AIRateLimitError),
    (500, AIProviderError),
    (503, AIProviderError),
    (418, AIProviderError),
    (301, AIProviderError),
])
def test_ac_ai_09_status_errors(status: int, error: type[AIError]) -> None:
    body = LEAK_BODY + " " + FAKE_KEY
    with pytest.raises(error) as info:
        _provider(FakeTransport(status=status, body=body)).complete(_request())
    assert type(info.value) is error
    assert (info.value.status, info.value.provider) == (status, "meta")
    assert str(status) in str(info.value)
    for leaked in (FAKE_KEY, "internal detail", "Top region"):
        assert leaked not in str(info.value)
        assert leaked not in repr(info.value)


@pytest.mark.parametrize(("exc", "error"), [
    (TimeoutError("timed out"), AITimeoutError),
    (ConnectionRefusedError("refused"), AIProviderError),
    (OSError("getaddrinfo failed for api.meta.ai"), AIProviderError),
    (http.client.RemoteDisconnected("closed"), AIProviderError),
    (http.client.IncompleteRead(b"partial"), AIProviderError),
])
def test_ac_ai_10_transport_failures(exc: BaseException, error: type[AIError]) -> None:
    with pytest.raises(error) as info:
        _provider(FakeTransport(exc=exc)).complete(_request())
    assert type(info.value) is error
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__
    assert FAKE_KEY not in str(info.value)


@pytest.mark.parametrize("body", [
    b"",
    b"not json",
    b"\xff\xfe",
    b"[1, 2]",
    b'"text"',
    b"{}",
    b'{"choices": []}',
    b'{"choices": {}}',
    b'{"choices": ["text"]}',
    b'{"choices": [{}]}',
    b'{"choices": [{"message": "text"}]}',
    b'{"choices": [{"message": {"content": null}}]}',
    b'{"choices": [{"message": {"content": 42}}]}',
    b'{"choices": [{"message": {"content": "ok"}, "finish_reason": 1}]}',
    b'{"choices": [{"message": {"content": "ok"}}], "model": 5}',
    b'{"choices": [{"message": {"content": "ok"}}], "usage": []}',
    b'{"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1}}',
    (b'{"choices": [{"message": {"content": "ok"}}], '
     b'"usage": {"prompt_tokens": "1", "completion_tokens": 2}}'),
    (b'{"choices": [{"message": {"content": "ok"}}], '
     b'"usage": {"prompt_tokens": 1.5, "completion_tokens": 2}}'),
    (b'{"choices": [{"message": {"content": "ok"}}], '
     b'"usage": {"prompt_tokens": true, "completion_tokens": 2}}'),
    (b'{"choices": [{"message": {"content": "ok"}}], '
     b'"usage": {"prompt_tokens": -1, "completion_tokens": 2}}'),
])
def test_ac_ai_11_invalid_responses(body: bytes) -> None:
    with pytest.raises(AIResponseError) as info:
        _provider(FakeTransport(body=body)).complete(_request())
    assert info.value.provider == "meta"
    assert info.value.__cause__ is None


def test_ac_ai_10_https_transport_refuses_plain_http() -> None:
    """The default transport refuses non-https URLs before opening anything."""
    with pytest.raises(ValueError, match="https"):
        https_transport("POST", "http://example.test/v1/chat/completions", {}, b"", 1.0)
