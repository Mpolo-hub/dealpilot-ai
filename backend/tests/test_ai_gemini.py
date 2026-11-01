"""Spec 006: Gemini provider settings, request, response and errors.

Criteria AC-GEM-01 to 09 and 21 to 24 (the "G" file of spec 006 section 11). Every test
uses a fake transport, a fake clock and a temporary usage folder: no socket, no real key,
no call to Google. Helpers are in gemini_support.py.
"""
from __future__ import annotations

import dataclasses
import functools
import importlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from dealpilot.ai import (
    AIAuthError,
    AIBillingError,
    AIBlockedError,
    AIBudgetError,
    AIConfigError,
    AIError,
    AIProviderError,
    AIRateLimitError,
    AIRequestError,
    AIResponseError,
    AISettings,
    AITimeoutError,
    Message,
    get_provider,
    load_settings,
)
from dealpilot.ai.gemini import GeminiProvider
from dealpilot.ai.meta import MAX_RESPONSE_BYTES, MetaProvider, ResponseTooLarge, https_transport
from dealpilot.ai.mock import MockProvider
from gemini_support import (
    FAKE_KEY,
    MODEL,
    FakeTransport,
    error_body,
    gemini_env,
    make_provider,
    read_entries,
    reply,
    request,
)

KEY_VAR = "DEALPILOT_GEMINI_API_KEY"
BASE = "https://generativelanguage.googleapis.com/v1beta"


def _sent(transport: FakeTransport) -> dict:
    return json.loads(transport.calls[0][3])


def _no_ledger(usage_dir: Path) -> bool:
    return not usage_dir.exists() or not any(usage_dir.iterdir())


# --------------------------------------------------------------------------- AC-GEM-01

def test_ac_gem_01_defaults(tmp_path: Path) -> None:
    s = load_settings(gemini_env(tmp_path / "usage"))
    assert (s.provider, s.gemini_model, s.gemini_base_url, s.gemini_data_class) == (
        "gemini", MODEL, BASE, "synthetic")
    assert (s.max_input_chars, s.max_output_tokens, s.monthly_budget_usd,
            s.max_calls_per_hour) == (16_000, 1_024, Decimal("5.00"), 30)
    assert (s.gemini_price_input, s.gemini_price_output) == (Decimal("0.30"), Decimal("2.50"))
    assert s.usage_dir == (tmp_path / "usage").resolve()
    plain = load_settings({})  # no model and no prices by default
    assert (plain.gemini_model, plain.gemini_price_input, plain.gemini_api_key) == (
        None, None, None)


@pytest.mark.parametrize("model", [None, "", "gemini-3.1-flash-lite", "gemini-3.5-flash",
                                   "GEMINI-3.5-FLASH-LITE", "muse-spark-1.3"])
def test_ac_gem_01_model_has_no_default_and_one_allowed_value(tmp_path, model) -> None:
    with pytest.raises(AIConfigError, match="DEALPILOT_GEMINI_MODEL"):
        load_settings(gemini_env(tmp_path, DEALPILOT_GEMINI_MODEL=model))


@pytest.mark.parametrize(("var", "value"), [
    ("DEALPILOT_GEMINI_BASE_URL", "http://generativelanguage.googleapis.com/v1beta"),
    ("DEALPILOT_GEMINI_BASE_URL", "generativelanguage.googleapis.com"),
    ("DEALPILOT_GEMINI_BASE_URL", "https://example.test:99999/v1"),
    ("DEALPILOT_GEMINI_DATA_CLASS", "public"),
    ("DEALPILOT_AI_TIMEOUT_SECONDS", "0"),
    ("DEALPILOT_AI_MONTHLY_BUDGET_USD", "lots"),
    ("DEALPILOT_AI_MAX_CALLS_PER_HOUR", "many"),
])
def test_ac_gem_01_invalid_values_name_the_variable(tmp_path, var, value) -> None:
    with pytest.raises(AIConfigError, match=var):
        load_settings(gemini_env(tmp_path, **{var: value}))


def test_ac_gem_01_base_url_trailing_slash(tmp_path) -> None:
    s = load_settings(gemini_env(tmp_path, DEALPILOT_GEMINI_BASE_URL="https://example.test/v1/"))
    assert s.gemini_base_url == "https://example.test/v1"


@pytest.mark.parametrize(("key", "message"), [
    (None, "is not set"),
    ("", "is not set"),
    ("short-key", "is malformed"),
    ("fake key with spaces " + "x" * 8, "is malformed"),
    ("fake-key-with-tab\t" + "x" * 8, "is malformed"),
    ("fake-key-with-bell\a" + "x" * 8, "is malformed"),
    ("fake-key-with-nul\0" + "x" * 8, "is malformed"),
])
def test_ac_gem_01_key_missing_or_malformed(tmp_path, key, message) -> None:
    with pytest.raises(AIConfigError, match=f"{KEY_VAR} {message}") as info:
        load_settings(gemini_env(tmp_path, **{KEY_VAR: key}))
    if key:
        assert key not in str(info.value)
        assert key not in repr(info.value)


@pytest.mark.parametrize("generic", ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
def test_ac_gem_01_generic_key_names_are_never_read(tmp_path, generic) -> None:
    env = gemini_env(tmp_path, **{KEY_VAR: None}) | {generic: FAKE_KEY}
    with pytest.raises(AIConfigError, match=f"{KEY_VAR} is not set"):
        load_settings(env)


def test_ac_gem_01_key_never_printed(tmp_path) -> None:
    s = load_settings(gemini_env(tmp_path))
    assert s.gemini_api_key.reveal() == FAKE_KEY
    for shown in (repr(s), str(s), repr(s.gemini_api_key), str(s.gemini_api_key),
                  f"{s.gemini_api_key}"):
        assert FAKE_KEY not in shown
        assert "g" * 16 not in shown


def test_ac_gem_01_key_alone_leaves_mock(tmp_path) -> None:
    env = {KEY_VAR: FAKE_KEY, "GEMINI_API_KEY": FAKE_KEY, "GOOGLE_API_KEY": FAKE_KEY}
    settings = load_settings(env)
    assert settings.provider == "mock"
    assert settings.gemini_api_key is None
    assert isinstance(get_provider(settings), MockProvider)


def test_ac_gem_01_provider_from_hand_built_settings_needs_every_value(tmp_path) -> None:
    good = load_settings(gemini_env(tmp_path))
    for field, var in [("gemini_api_key", KEY_VAR), ("gemini_model", "DEALPILOT_GEMINI_MODEL"),
                       ("usage_dir", "DEALPILOT_AI_USAGE_DIR"),
                       ("gemini_price_input", "DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK")]:
        with pytest.raises(AIConfigError, match=var):
            GeminiProvider(dataclasses.replace(good, **{field: None}))
    with pytest.raises(AIConfigError, match="DEALPILOT_GEMINI_MODEL"):
        GeminiProvider(dataclasses.replace(good, gemini_model="gemini-3.5-flash"))


# --------------------------------------------------------------------------- AC-GEM-02

@pytest.mark.parametrize("base", ["https://example.test/v1beta", "https://example.test/v1beta/"])
def test_ac_gem_02_request_shape(tmp_path, base) -> None:
    transport = FakeTransport()
    provider = make_provider(tmp_path, transport, DEALPILOT_GEMINI_BASE_URL=base)
    provider.complete(request(messages=[Message("system", "Be brief."), Message("user", "Hi")]))
    method, url, headers, body, timeout = transport.calls[0]
    assert method == "POST"
    assert url == f"https://example.test/v1beta/models/{MODEL}:generateContent"
    assert "?" not in url and FAKE_KEY not in url
    assert headers == {"x-goog-api-key": FAKE_KEY, "Content-Type": "application/json"}
    assert not any(h.lower() == "authorization" for h in headers)
    sent = json.loads(body)
    assert set(sent) == {"contents", "generationConfig", "systemInstruction"}
    assert sent["generationConfig"] == {"maxOutputTokens": 100, "temperature": 0.0}
    text = body.decode("utf-8")
    for field in ("thinking", "store", "candidateCount", "tools", "safetySettings",
                  "cachedContent", "toolConfig"):
        assert field not in text
    assert timeout == 30.0


def test_ac_gem_02_no_system_instruction_without_system_message(tmp_path) -> None:
    transport = FakeTransport()
    make_provider(tmp_path, transport).complete(request())
    assert set(_sent(transport)) == {"contents", "generationConfig"}


# --------------------------------------------------------------------------- AC-GEM-03

def test_ac_gem_03_role_mapping_and_merge(tmp_path) -> None:
    transport = FakeTransport()
    texts = ["first user", "  second user, spaces kept  ", "first model", "second model",
             "last user"]
    messages = [Message("system", "rule one"), Message("system", "rule two"),
                Message("user", texts[0]), Message("user", texts[1]),
                Message("assistant", texts[2]), Message("assistant", texts[3]),
                Message("user", texts[4])]
    make_provider(tmp_path, transport).complete(request(messages=messages))
    sent = _sent(transport)
    assert sent["systemInstruction"] == {"parts": [{"text": "rule one"}, {"text": "rule two"}]}
    assert sent["contents"] == [
        {"role": "user", "parts": [{"text": texts[0]}, {"text": texts[1]}]},
        {"role": "model", "parts": [{"text": texts[2]}, {"text": texts[3]}]},
        {"role": "user", "parts": [{"text": texts[4]}]},
    ]


@pytest.mark.parametrize("messages", [
    [Message("user", "a"), Message("system", "late rule"), Message("user", "b")],
    [Message("assistant", "I start"), Message("user", "b")],
    [Message("system", "rule"), Message("assistant", "I start"), Message("user", "b")],
])
def test_ac_gem_03_refused_before_ledger_and_transport(tmp_path, messages) -> None:
    transport = FakeTransport()
    usage = tmp_path / "usage"
    with pytest.raises(AIRequestError):
        make_provider(usage, transport).complete(request(messages=messages))
    assert transport.calls == []
    assert _no_ledger(usage)


# --------------------------------------------------------------------------- AC-GEM-04

def test_ac_gem_04_text_usage_and_thought_parts(tmp_path) -> None:
    parts = [{"text": "Sales "}, {"thought": True, "text": "private reasoning"},
             {"inlineData": {"mimeType": "x"}}, {"thought": False, "text": "rose 4%."},
             {"text": "", "thoughtSignature": "opaque"}]
    body = reply(parts=parts, usage=(12, 7, 30),
                 candidates=[{"content": {"parts": parts}, "finishReason": "STOP"},
                             {"content": {"parts": [{"text": "other candidate"}]},
                              "finishReason": "STOP"}])
    result = make_provider(tmp_path, FakeTransport(body=body)).complete(request())
    assert result.text == "Sales rose 4%."
    assert (result.provider, result.model, result.finish_reason) == ("gemini", MODEL, "stop")
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (12, 7 + 30)


def test_ac_gem_04_thoughts_count_zero_when_absent(tmp_path) -> None:
    result = make_provider(tmp_path, FakeTransport(body=reply(usage=(12, 7, None)))).complete(
        request())
    assert result.usage.completion_tokens == 7


def test_ac_gem_04_thought_marker_must_be_boolean(tmp_path) -> None:
    body = reply(parts=[{"thought": "yes", "text": "maybe a thought"}])
    with pytest.raises(AIResponseError):
        make_provider(tmp_path, FakeTransport(body=body)).complete(request())


def test_ac_gem_04_only_thinking_is_refused_but_settled(tmp_path) -> None:
    body = reply(parts=[{"thought": True, "text": "all the budget went here"}],
                 finish="MAX_TOKENS", usage=(12, 0, 100))
    with pytest.raises(AIResponseError, match="empty reply"):
        make_provider(tmp_path, FakeTransport(body=body)).complete(request())
    [settled] = read_entries(tmp_path)
    assert settled["state"] == "settled"
    assert (settled["prompt_tokens"], settled["output_tokens"], settled["thoughts_tokens"]) == (
        12, 0, 100)
    # 12 x 0.30 + 100 x 2.50 = 253.6 per 1M tokens = 0.0002536 USD, stored with 6 decimals
    # and rounded up so a stored cost is never below the real one.
    assert settled["cost_usd"] == "0.000254"


# --------------------------------------------------------------------------- AC-GEM-05

@pytest.mark.parametrize(("status", "error"), [
    (301, AIProviderError), (400, AIProviderError), (401, AIAuthError), (402, AIBillingError),
    (403, AIAuthError), (404, AIConfigError), (416, AIProviderError), (429, AIRateLimitError),
    (499, AIProviderError), (500, AIProviderError), (503, AIProviderError),
    (504, AIProviderError),
])
def test_ac_gem_05_status_mapping(tmp_path, status, error) -> None:
    with pytest.raises(error) as info:
        make_provider(tmp_path, FakeTransport(status=status, body=error_body(status))).complete(
            request())
    assert type(info.value) is error
    assert (info.value.status, info.value.provider, info.value.reason) == (
        status, "gemini", None)
    shown = str(info.value) + repr(info.value)
    for secret in ("internal secret detail", FAKE_KEY, "INVALID_ARGUMENT", "googleapis",
                   "generateContent"):
        assert secret not in shown
    if status == 404:
        assert "model not found" in str(info.value)


@pytest.mark.parametrize("code", ["invalid_request", "api_error", 400, None, "x" * 65])
def test_ac_gem_05_reason_is_never_taken_from_error_code(tmp_path, code) -> None:
    """D18: the documented format of `error.code` is an integer (F5), which never meets the
    section 6 rule, so `reason` stays None for every value."""
    body = json.dumps({"error": {"code": code, "status": "INVALID_ARGUMENT"}}).encode()
    with pytest.raises(AIProviderError) as info:
        make_provider(tmp_path, FakeTransport(status=400, body=body)).complete(request())
    assert info.value.reason is None


def test_ac_gem_05_errors_without_reason_keep_working() -> None:
    for error_class in (AIError, AIConfigError, AIProviderError, AIBlockedError, AIBudgetError):
        error = error_class("plain message")
        assert (str(error), error.provider, error.status, error.reason) == (
            "plain message", None, None, None)
        assert isinstance(error, AIError)
    assert AIBlockedError("x", provider="gemini", reason="SAFETY").reason == "SAFETY"


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _slow_connection_factory(clock: _Clock, chunks: int, seconds_per_read: float):
    """A fake HTTPS connection whose reads each take `seconds_per_read` of fake time."""
    class Response:
        status = 200
        left = chunks

        def getheader(self, name, default=None):
            return default

        def read1(self, n):
            clock.now += seconds_per_read
            if self.left == 0:
                return b""
            self.left -= 1
            return b" "

    class Sock:
        def settimeout(self, seconds):
            assert seconds > 0

    class Conn:
        def __init__(self, host, port, timeout, context) -> None:
            self.sock = None

        def connect(self) -> None:
            self.sock = Sock()

        def request(self, method, path, body=None, headers=None) -> None:
            pass

        def getresponse(self):
            return Response()

        def close(self) -> None:
            pass

    return Conn


def test_ac_gem_05_shared_total_deadline(tmp_path) -> None:
    clock = _Clock()
    transport = functools.partial(https_transport,
                                  connection_factory=_slow_connection_factory(clock, 10, 0.4),
                                  clock=clock)
    provider = make_provider(tmp_path, transport, DEALPILOT_AI_TIMEOUT_SECONDS="2")
    with pytest.raises(AITimeoutError):  # each read 0.4 s, all reads together over 2 s
        provider.complete(request())
    assert [f.name for f in dataclasses.fields(AISettings) if "timeout" in f.name] == [
        "timeout_seconds"]
    ignored = load_settings(gemini_env(tmp_path, DEALPILOT_GEMINI_TIMEOUT_SECONDS="1"))
    assert ignored.timeout_seconds == 30.0


# --------------------------------------------------------------------------- AC-GEM-06

@pytest.mark.parametrize("code", ["SAFETY", "OTHER", "BLOCKLIST", "PROHIBITED_CONTENT"])
def test_ac_gem_06_prompt_block_reason(tmp_path, code) -> None:
    body = reply(text=None, finish=None, promptFeedback={"blockReason": code}, candidates=[])
    with pytest.raises(AIBlockedError) as info:
        make_provider(tmp_path, FakeTransport(body=body)).complete(request())
    assert info.value.reason == code
    assert str(info.value) == "content blocked by the provider"


@pytest.mark.parametrize("finish", ["SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT",
                                    "SPII"])
def test_ac_gem_06_blocked_finish_reasons(tmp_path, finish) -> None:
    with pytest.raises(AIBlockedError) as info:
        make_provider(tmp_path, FakeTransport(body=reply(finish=finish))).complete(request())
    assert info.value.reason == finish


@pytest.mark.parametrize("finish", ["OTHER", "LANGUAGE", "SOMETHING_NEW", "", None])
def test_ac_gem_06_other_finish_reasons(tmp_path, finish) -> None:
    with pytest.raises(AIResponseError):
        make_provider(tmp_path, FakeTransport(body=reply(finish=finish))).complete(request())


# --------------------------------------------------------------------------- AC-GEM-07

TOO_LARGE = b" " * (MAX_RESPONSE_BYTES + 1)
INVALID_BODIES = {
    "not json": (200, b"not json"),
    "not utf-8": (200, b"\xff\xfe"),
    "json list": (200, b"[1, 2]"),
    "no candidates": (200, json.dumps({"candidates": []}).encode()),
    "usage only": (200, json.dumps({"usageMetadata": {"promptTokenCount": 1,
                                                      "candidatesTokenCount": 1}}).encode()),
    "negative count": (200, reply(usage=(-1, 5, None))),
    "text count": (200, reply(usage=(10, 5, 2)).replace(b'"thoughtsTokenCount": 2',
                                                        b'"thoughtsTokenCount": "2"')),
    "usage not object": (200, json.dumps({"candidates": [{}], "usageMetadata": "many"})
                         .encode()),
    "over 1 MiB": (200, TOO_LARGE),
    "over 1 MiB, status 500": (500, TOO_LARGE),
}


@pytest.mark.parametrize("case", list(INVALID_BODIES))
def test_ac_gem_07_invalid_bodies(tmp_path, case) -> None:
    status, body = INVALID_BODIES[case]
    with pytest.raises(AIResponseError):
        make_provider(tmp_path, FakeTransport(status=status, body=body)).complete(request())


MIXED_CASES = {
    "blocked prompt, negative count": (
        {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}, (5, -1, None)),
    "blocked prompt, missing candidates count": (
        {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}, "incomplete"),
    "blocked finish reason, bad count": ({}, (5, 3, -2)),
}


@pytest.mark.parametrize("case", list(MIXED_CASES))
def test_ac_gem_07_invalid_usage_wins_over_a_block(tmp_path, case) -> None:
    """Invalid usage is checked first: AIResponseError, and the reservation is kept."""
    extra, usage = MIXED_CASES[case]
    if usage == "incomplete":
        body = reply(text=None, finish=None, usage=None, **extra,
                     usageMetadata={"promptTokenCount": 5})
    else:
        body = reply(finish="SAFETY", usage=usage, **extra)
    with pytest.raises(AIResponseError, match="usage counts"):
        make_provider(tmp_path, FakeTransport(body=body)).complete(request())
    [stored] = read_entries(tmp_path)
    assert stored["state"] == "kept"


def test_ac_gem_07_valid_usage_keeps_the_block(tmp_path) -> None:
    body = reply(text=None, finish=None, usage=(5, 0, None),
                 promptFeedback={"blockReason": "SAFETY"}, candidates=[])
    with pytest.raises(AIBlockedError):
        make_provider(tmp_path, FakeTransport(body=body)).complete(request())
    [stored] = read_entries(tmp_path)
    assert stored["state"] == "settled"


def test_ac_gem_07_transport_size_limit(tmp_path) -> None:
    with pytest.raises(AIResponseError, match="too large"):
        make_provider(tmp_path, FakeTransport(error=ResponseTooLarge())).complete(request())


# --------------------------------------------------------------------------- AC-GEM-08

@pytest.mark.parametrize(("text", "finish"), [
    ("", "STOP"), ("   \n\t", "STOP"), ("", "MAX_TOKENS"), (None, "MAX_TOKENS"),
    ("Partial answ", "CONTINUATION"),
])
def test_ac_gem_08_empty_or_partial_replies(tmp_path, text, finish) -> None:
    with pytest.raises(AIResponseError):
        make_provider(tmp_path, FakeTransport(body=reply(text=text, finish=finish))).complete(
            request())


def test_ac_gem_08_max_tokens_with_text_is_length(tmp_path) -> None:
    result = make_provider(tmp_path, FakeTransport(body=reply("Cut here", "MAX_TOKENS"))
                           ).complete(request())
    assert (result.text, result.finish_reason) == ("Cut here", "length")


# --------------------------------------------------------------------------- AC-GEM-09

EMOJI = "\U0001F600"  # 1 code point, 4 UTF-8 bytes


def _sized(chars: int) -> list[Message]:
    """`chars` code points across a system and a user message, with emojis."""
    first = "s" * 100 + EMOJI * 100
    return [Message("system", first), Message("user", "u" * (chars - 200))]


@pytest.mark.parametrize(("chars", "ok"), [(16_000, True), (16_001, False)])
def test_ac_gem_09_default_input_limit(tmp_path, chars, ok) -> None:
    transport = FakeTransport()
    provider = make_provider(tmp_path / "usage", transport)
    if ok:
        provider.complete(request(messages=_sized(chars)))
        assert len(transport.calls) == 1
    else:
        with pytest.raises(AIRequestError):
            provider.complete(request(messages=_sized(chars)))
        assert transport.calls == []
        assert _no_ledger(tmp_path / "usage")


@pytest.mark.parametrize(("max_tokens", "ok"), [(1_024, True), (1_025, False)])
def test_ac_gem_09_default_output_limit(tmp_path, max_tokens, ok) -> None:
    transport = FakeTransport()
    provider = make_provider(tmp_path / "usage", transport)
    if ok:
        provider.complete(request(max_tokens=max_tokens))
    else:
        with pytest.raises(AIRequestError):
            provider.complete(request(max_tokens=max_tokens))
        assert _no_ledger(tmp_path / "usage")
    assert len(transport.calls) == int(ok)


def test_ac_gem_09_lower_settings_move_the_limits(tmp_path) -> None:
    transport = FakeTransport()
    provider = make_provider(tmp_path, transport, DEALPILOT_AI_MAX_INPUT_CHARS="10000",
                             DEALPILOT_AI_MAX_OUTPUT_TOKENS="512")
    provider.complete(request(messages=_sized(10_000), max_tokens=512))
    for kwargs in ({"messages": _sized(10_001)}, {"max_tokens": 513}):
        with pytest.raises(AIRequestError):
            provider.complete(request(**kwargs))
    assert len(transport.calls) == 1


def test_ac_gem_09_smallest_settings(tmp_path) -> None:
    transport = FakeTransport()
    provider = make_provider(tmp_path, transport, DEALPILOT_AI_MAX_INPUT_CHARS="1",
                             DEALPILOT_AI_MAX_OUTPUT_TOKENS="1")
    provider.complete(request("a", max_tokens=1))
    with pytest.raises(AIRequestError):
        provider.complete(request("ab", max_tokens=1))
    assert len(transport.calls) == 1


@pytest.mark.parametrize("var", ["DEALPILOT_AI_MAX_INPUT_CHARS",
                                 "DEALPILOT_AI_MAX_OUTPUT_TOKENS"])
@pytest.mark.parametrize("value", ["0", "16001", "1025", "-1", "1.5", "nan", "inf", "ten",
                                   " 10", "1e3"])
def test_ac_gem_09_invalid_limit_settings(tmp_path, var, value) -> None:
    if var.endswith("CHARS") and value == "1025":
        value = "16001"  # 1,025 is a valid input limit
    with pytest.raises(AIConfigError, match=var):
        load_settings(gemini_env(tmp_path, **{var: value}))


@pytest.mark.parametrize("messages", [
    [Message("user", "Sales \ud800 rose")],
    [Message("system", "rule \udfff"), Message("user", "fine")],
])
def test_ac_gem_09_lone_surrogate_refused(tmp_path, messages) -> None:
    transport = FakeTransport()
    usage = tmp_path / "usage"
    originals = [m.content for m in messages]
    with pytest.raises(AIRequestError, match="lone surrogate"):
        make_provider(usage, transport).complete(request(messages=messages))
    assert transport.calls == []
    assert _no_ledger(usage)
    assert [m.content for m in messages] == originals


def test_ac_gem_09_mock_has_no_limits(tmp_path) -> None:
    mock = get_provider(load_settings({"DEALPILOT_AI_USAGE_DIR": str(tmp_path / "usage")}))
    result = mock.complete(request("x" * 16_001, max_tokens=4_096))
    assert result.provider == "mock"
    assert not (tmp_path / "usage").exists()


# --------------------------------------------------------------------------- AC-GEM-21

@pytest.mark.parametrize(("var", "value"), [
    ("DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK", None),
    ("DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK", None),
    ("DEALPILOT_GEMINI_PRICES_CHECKED_ON", None),
    ("DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK", ""),
    ("DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK", "0"),
    ("DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK", "0.00"),
    ("DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK", "-0.30"),
    ("DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK", "cheap"),
    ("DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK", "nan"),
    ("DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK", "inf"),
    ("DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK", "1000.01"),
    ("DEALPILOT_GEMINI_PRICES_CHECKED_ON", "2026-13-01"),
    ("DEALPILOT_GEMINI_PRICES_CHECKED_ON", "31/10/2026"),
    ("DEALPILOT_GEMINI_PRICES_CHECKED_ON", "2999-01-01"),
])
def test_ac_gem_21_invalid_prices(tmp_path, var, value) -> None:
    with pytest.raises(AIConfigError, match=var):
        load_settings(gemini_env(tmp_path / "usage", **{var: value}))
    assert not (tmp_path / "usage").exists()


def test_ac_gem_21_entry_stores_prices(tmp_path) -> None:
    make_provider(tmp_path, FakeTransport()).complete(request())
    [stored] = read_entries(tmp_path)
    assert (stored["price_input_usd_per_mtok"], stored["price_output_usd_per_mtok"],
            stored["prices_checked_on"]) == ("0.30", "2.50", "2026-10-30")


# --------------------------------------------------------------------------- AC-GEM-22

@pytest.mark.parametrize("value", [None, "", "public", "SYNTHETIC", "real "])
def test_ac_gem_22_data_class_required(tmp_path, value) -> None:
    with pytest.raises(AIConfigError, match="DEALPILOT_GEMINI_DATA_CLASS"):
        load_settings(gemini_env(tmp_path, DEALPILOT_GEMINI_DATA_CLASS=value))


@pytest.mark.parametrize("value", ["synthetic", "real"])
def test_ac_gem_22_data_class_values(tmp_path, value) -> None:
    s = load_settings(gemini_env(tmp_path, DEALPILOT_GEMINI_DATA_CLASS=value))
    assert s.gemini_data_class == value


def test_ac_gem_22_no_effect_on_mock_or_meta() -> None:
    for provider, extra in (("mock", {}),
                            ("meta", {"DEALPILOT_META_API_KEY": FAKE_KEY})):
        env = {"DEALPILOT_AI_PROVIDER": provider, "DEALPILOT_GEMINI_DATA_CLASS": "public"}
        assert load_settings(env | extra).gemini_data_class is None


# --------------------------------------------------------------------------- AC-GEM-23

@pytest.mark.parametrize("transport", [
    FakeTransport(status=503, body=error_body(503)),
    FakeTransport(status=429, body=error_body(429)),
    FakeTransport(error=TimeoutError()),
    FakeTransport(error=ConnectionResetError()),
    FakeTransport(body=reply(finish="SAFETY")),
])
def test_ac_gem_23_no_retry_no_fallback(tmp_path, monkeypatch, transport) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("another provider was called")

    monkeypatch.setattr(MetaProvider, "complete", forbidden)
    monkeypatch.setattr(MockProvider, "complete", forbidden)
    with pytest.raises(AIError):
        make_provider(tmp_path, transport).complete(request())
    assert len(transport.calls) == 1


# --------------------------------------------------------------------------- AC-GEM-24

NO_NETWORK_SCRIPT = """
import socket, sys
def no_network(*args, **kwargs):
    raise AssertionError("network access attempted")
socket.socket.connect = no_network
socket.create_connection = no_network
import dealpilot.ai as ai
import dealpilot.ai.budget, dealpilot.ai.gemini
request = ai.CompletionRequest([ai.Message("user", "hi")])
ai.get_provider(ai.load_settings({})).complete(request)
env = {"DEALPILOT_AI_PROVIDER": "gemini", "DEALPILOT_GEMINI_API_KEY": "fake-test-" + "g" * 16,
       "DEALPILOT_GEMINI_MODEL": "gemini-3.5-flash-lite", "DEALPILOT_GEMINI_DATA_CLASS":
       "synthetic", "DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK": "0.30",
       "DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK": "2.50",
       "DEALPILOT_GEMINI_PRICES_CHECKED_ON": "2026-10-30", "DEALPILOT_AI_USAGE_DIR": sys.argv[1]}
provider = ai.get_provider(ai.load_settings(env))
assert type(provider).__name__ == "GeminiProvider"
print("ok")
"""


def test_ac_gem_24_import_opens_no_connection(tmp_path) -> None:
    result = subprocess.run([sys.executable, "-c", NO_NETWORK_SCRIPT, str(tmp_path / "u")],
                            capture_output=True, text=True, check=False, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
    assert not (tmp_path / "u").exists()  # building the provider writes nothing


def test_ac_gem_24_api_unchanged() -> None:
    from dealpilot.api.main import app

    paths = set(app.openapi()["paths"]) | {getattr(r, "path", "") for r in app.routes}
    assert not [p for p in paths if any(w in p.lower() for w in ("/ai", "gemini", "llm",
                                                                  "chat", "complet"))]
    api_dir = Path(importlib.import_module("dealpilot.api").__file__).parent
    for source in api_dir.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "dealpilot.ai" not in text and "gemini" not in text.lower(), source.name


def test_ac_gem_24_meta_empty_reply_unchanged(tmp_path) -> None:
    body = json.dumps({"choices": [{"message": {"content": ""}}]}).encode()
    meta = MetaProvider(load_settings({"DEALPILOT_AI_PROVIDER": "meta",
                                       "DEALPILOT_META_API_KEY": FAKE_KEY}),
                        transport=FakeTransport(body=body))
    assert meta.complete(request()).text == ""
