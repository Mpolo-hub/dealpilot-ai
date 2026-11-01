"""Spec 004: settings, request types, mock provider and registry (AC-AI-01 to 06, 12, 13).

No test opens a network connection. Fake keys are built at run time so the repository
secret scan (test_security.py) never sees a key-shaped literal.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from dealpilot.ai import (
    AIConfigError,
    AIProvider,
    AIRequestError,
    AISettings,
    CompletionRequest,
    CompletionResult,
    Message,
    factory,
    get_provider,
    load_settings,
)
from dealpilot.ai.meta import MetaProvider
from dealpilot.ai.mock import MockProvider

FAKE_KEY = "fake-test-" + "k" * 16
KEY_VAR = "DEALPILOT_META_API_KEY"


def _request(text: str = "Summarize last month's sales.") -> CompletionRequest:
    return CompletionRequest([Message("system", "Be brief."), Message("user", text)])


# --------------------------------------------------------------------------- settings

def test_ac_ai_01_defaults() -> None:
    s = load_settings({})
    assert (s.provider, s.model, s.timeout_seconds, s.meta_base_url, s.meta_api_key) == (
        "mock", "muse-spark-1.3", 30.0, "https://api.meta.ai/v1", None)


def test_ac_ai_01_empty_values_count_as_unset() -> None:
    env = {"DEALPILOT_AI_PROVIDER": "", "DEALPILOT_AI_MODEL": "",
           "DEALPILOT_AI_TIMEOUT_SECONDS": "", "DEALPILOT_META_BASE_URL": ""}
    assert load_settings(env) == load_settings({})


def test_ac_ai_01_reads_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEALPILOT_AI_TIMEOUT_SECONDS", "45")
    monkeypatch.delenv("DEALPILOT_AI_PROVIDER", raising=False)
    monkeypatch.delenv("DEALPILOT_AI_MODEL", raising=False)
    monkeypatch.delenv("DEALPILOT_META_BASE_URL", raising=False)
    assert load_settings().timeout_seconds == 45.0


@pytest.mark.parametrize(("var", "value"), [
    ("DEALPILOT_AI_PROVIDER", "openai"),
    ("DEALPILOT_AI_PROVIDER", "Mock"),
    ("DEALPILOT_AI_MODEL", "muse-spark-9"),
    ("DEALPILOT_AI_TIMEOUT_SECONDS", "fast"),
    ("DEALPILOT_AI_TIMEOUT_SECONDS", "0"),
    ("DEALPILOT_AI_TIMEOUT_SECONDS", "121"),
    ("DEALPILOT_AI_TIMEOUT_SECONDS", "nan"),
    ("DEALPILOT_META_BASE_URL", "http://api.meta.ai/v1"),
    ("DEALPILOT_META_BASE_URL", "https://"),
    ("DEALPILOT_META_BASE_URL", "api.meta.ai/v1"),
    ("DEALPILOT_META_BASE_URL", "https://api.meta.ai:99999/v1"),
    ("DEALPILOT_META_BASE_URL", "https://api.meta.ai:port/v1"),
    ("DEALPILOT_META_BASE_URL", "https://[::1/v1"),
])
def test_ac_ai_02_invalid_settings(var: str, value: str) -> None:
    with pytest.raises(AIConfigError, match=var):
        load_settings({var: value})


@pytest.mark.parametrize("timeout", ["1", "120", "2.5"])
def test_ac_ai_02_timeout_bounds_are_inclusive(timeout: str) -> None:
    assert load_settings({"DEALPILOT_AI_TIMEOUT_SECONDS": timeout}).timeout_seconds == float(
        timeout)


def test_ac_ai_02_base_url_with_port_and_trailing_slash() -> None:
    url = load_settings({"DEALPILOT_META_BASE_URL": "https://example.test:8443/v1/"})
    assert url.meta_base_url == "https://example.test:8443/v1"


@pytest.mark.parametrize("key", [None, "", "short", "has space " + "x" * 16])
def test_ac_ai_03_mock_needs_no_key(key: str | None) -> None:
    env = {} if key is None else {KEY_VAR: key}
    settings = load_settings(env)
    assert settings.meta_api_key is None
    first = get_provider(settings).complete(_request())
    second = get_provider(load_settings(env)).complete(_request())
    assert isinstance(first, CompletionResult)
    assert first == second


def test_ac_ai_03_mock_reply() -> None:
    result = MockProvider(load_settings({})).complete(_request("hello world " * 50))
    expected = "[mock:muse-spark-1.3] " + ("hello world " * 50)[:200]
    assert result.text == expected
    assert (result.provider, result.model, result.finish_reason) == (
        "mock", "muse-spark-1.3", "stop")
    assert result.usage.prompt_tokens == 2 + 100
    assert result.usage.completion_tokens == len(expected.split())


@pytest.mark.parametrize(("key", "message"), [
    (None, "is not set"),
    ("", "is not set"),
    ("short-key", "is malformed"),
    ("fake key with spaces " + "x" * 8, "is malformed"),
    ("fake-key-with-newline" + "\n", "is malformed"),
    ("fake-key-with-tab\t" + "x" * 8, "is malformed"),
])
def test_ac_ai_04_meta_key_missing_or_malformed(key: str | None, message: str) -> None:
    env = {"DEALPILOT_AI_PROVIDER": "meta"} | ({} if key is None else {KEY_VAR: key})
    with pytest.raises(AIConfigError, match=f"{KEY_VAR} {message}") as info:
        load_settings(env)
    if key:
        assert key not in str(info.value)
        assert key.strip() not in repr(info.value)


def test_ac_ai_04_meta_provider_without_key_in_settings() -> None:
    with pytest.raises(AIConfigError, match="is not set"):
        MetaProvider(AISettings(provider="meta"))


def test_ac_ai_05_key_never_printed() -> None:
    settings = load_settings({"DEALPILOT_AI_PROVIDER": "meta", KEY_VAR: FAKE_KEY})
    assert settings.meta_api_key.reveal() == FAKE_KEY
    for shown in (repr(settings), str(settings), repr(settings.meta_api_key),
                  str(settings.meta_api_key), f"{settings.meta_api_key}"):
        assert FAKE_KEY not in shown
        assert "k" * 16 not in shown


# --------------------------------------------------------------------------- requests

@pytest.mark.parametrize("build", [
    lambda: CompletionRequest([]),
    lambda: CompletionRequest([Message("assistant", "hi")]),
    lambda: CompletionRequest([Message("user", "hi"), Message("system", "x")]),
    lambda: CompletionRequest(["just text"]),
    lambda: CompletionRequest(None),
    lambda: CompletionRequest("user: hi"),
    lambda: CompletionRequest(Message("user", "hi")),
    lambda: CompletionRequest([Message("user", "hi")], max_tokens=0),
    lambda: CompletionRequest([Message("user", "hi")], max_tokens=4097),
    lambda: CompletionRequest([Message("user", "hi")], max_tokens=True),
    lambda: CompletionRequest([Message("user", "hi")], max_tokens=10.0),
    lambda: CompletionRequest([Message("user", "hi")], temperature=-0.1),
    lambda: CompletionRequest([Message("user", "hi")], temperature=2.1),
    lambda: CompletionRequest([Message("user", "hi")], temperature="0.5"),
    lambda: Message("tool", "hi"),
    lambda: Message("user", ""),
    lambda: Message("user", "   "),
    lambda: Message("user", None),
])
def test_ac_ai_06_invalid_requests(build) -> None:
    with pytest.raises(AIRequestError):
        build()


def test_ac_ai_06_valid_request_bounds() -> None:
    low = CompletionRequest([Message("user", "hi")], max_tokens=1, temperature=0)
    high = CompletionRequest((Message("user", "hi"),), max_tokens=4096, temperature=2.0)
    assert isinstance(low.messages, tuple)
    assert (low.max_tokens, high.max_tokens, high.temperature) == (1, 4096, 2.0)


# --------------------------------------------------------------------------- registry

def test_ac_ai_12_registry_selects_provider() -> None:
    assert isinstance(get_provider(load_settings({})), MockProvider)
    meta = get_provider(load_settings({"DEALPILOT_AI_PROVIDER": "meta", KEY_VAR: FAKE_KEY}))
    assert isinstance(meta, MetaProvider)


def test_ac_ai_12_get_provider_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DEALPILOT_AI_PROVIDER", "DEALPILOT_AI_MODEL", "DEALPILOT_AI_TIMEOUT_SECONDS",
                "DEALPILOT_META_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    assert isinstance(get_provider(), MockProvider)


def test_ac_ai_12_new_provider_without_changing_callers(monkeypatch) -> None:
    class EchoProvider(AIProvider):
        name = "echo"

        def complete(self, request: CompletionRequest) -> CompletionResult:
            return CompletionResult(request.messages[-1].content, self.name, self.settings.model)

    def business_logic(settings: AISettings) -> str:  # a caller that knows no provider
        return get_provider(settings).complete(_request("ping")).text

    monkeypatch.setitem(factory.REGISTRY, "echo", EchoProvider)
    assert business_logic(AISettings(provider="echo")) == "ping"
    assert business_logic(AISettings()).startswith("[mock:")


def test_ac_ai_12_unknown_provider_in_settings() -> None:
    with pytest.raises(AIConfigError, match="unknown AI provider"):
        get_provider(AISettings(provider="nobody"))


# --------------------------------------------------------------------------- isolation

NO_NETWORK_SCRIPT = """
import socket
def no_network(*args, **kwargs):
    raise AssertionError("network access attempted")
socket.socket.connect = no_network
socket.create_connection = no_network
import dealpilot.ai as ai
request = ai.CompletionRequest([ai.Message("user", "hi")])
ai.get_provider(ai.load_settings({})).complete(request)
ai.get_provider(ai.load_settings({"DEALPILOT_AI_PROVIDER": "meta",
                                  "DEALPILOT_META_API_KEY": "fake-test-" + "k" * 16}))
print("ok")
"""


def test_ac_ai_13_import_opens_no_connection() -> None:
    """In a fresh interpreter with sockets disabled: import, mock call, Meta setup."""
    result = subprocess.run([sys.executable, "-c", NO_NETWORK_SCRIPT], capture_output=True,
                            text=True, check=False, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_ac_ai_13_api_unchanged() -> None:
    from dealpilot.api.main import app

    paths = set(app.openapi()["paths"]) | {getattr(r, "path", "") for r in app.routes}
    assert not [p for p in paths if any(w in p.lower() for w in ("/ai", "llm", "chat",
                                                                  "complet", "meta-"))]
    api_dir = Path(importlib.import_module("dealpilot.api").__file__).parent
    for source in api_dir.glob("*.py"):
        assert "dealpilot.ai" not in source.read_text(encoding="utf-8"), source.name
