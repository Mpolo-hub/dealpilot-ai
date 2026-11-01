"""Spec 004 amendment P4: response size limit and total deadline (AC-AI-14, AC-AI-15).

`https_transport` runs with a fake HTTPS connection and a fake clock, so no socket is ever
opened. Fake keys are built at run time (see test_ai_config.py).
"""
from __future__ import annotations

import http.client

import pytest

from dealpilot.ai import (
    AIResponseError,
    AITimeoutError,
    CompletionRequest,
    Message,
    load_settings,
)
from dealpilot.ai.meta import (
    MAX_RESPONSE_BYTES,
    READ_CHUNK,
    MetaProvider,
    ResponseTooLarge,
    https_transport,
)

URL = "https://example.test/v1/chat/completions"
FAKE_KEY = "fake-test-" + "k" * 16
SECRET = b"internal secret detail "
OK_JSON = b'{"choices": [{"message": {"content": "ok"}}]}'


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, seconds: float) -> None:
        self.timeouts.append(seconds)


class FakeResponse:
    def __init__(self, status: int, chunks: list[bytes], headers: dict, clock: FakeClock,
                 seconds_per_read: float) -> None:
        self.status = status
        self._chunks = list(chunks)
        self._headers = headers
        self._clock = clock
        self._seconds = seconds_per_read
        self.requested: list[int] = []

    def getheader(self, name: str, default=None):
        return self._headers.get(name, default)

    def read1(self, n: int) -> bytes:
        self.requested.append(n)
        self._clock.now += self._seconds
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        if len(chunk) > n:  # hand back the rest on the next read
            self._chunks.insert(0, chunk[n:])
            chunk = chunk[:n]
        return chunk


class FakeConnectionFactory:
    """Builds one fake HTTPS connection and remembers it."""

    def __init__(self, status=200, chunks=(OK_JSON,), headers=None, seconds_per_read=0.0,
                 request_seconds=0.0, request_error: BaseException | None = None,
                 connect_seconds=0.0) -> None:
        self.clock = FakeClock()
        self.status, self.chunks, self.headers = status, list(chunks), headers or {}
        self.seconds_per_read, self.request_seconds = seconds_per_read, request_seconds
        self.connect_seconds = connect_seconds
        self.request_error = request_error
        self.conn = None

    def __call__(self, host, port, timeout, context):
        factory = self

        class Conn:
            def __init__(self) -> None:
                self.host, self.port, self.timeout, self.context = host, port, timeout, context
                self.sock = None  # like http.client: no socket before connect()
                self.closed = False
                self.response = None
                self.calls: list[str] = []

            def connect(self) -> None:
                self.calls.append("connect")
                factory.clock.now += factory.connect_seconds
                self.sock = FakeSocket()

            def request(self, method, path, body=None, headers=None):
                self.calls.append("request")
                assert self.sock is not None, "request before connect would reconnect"
                factory.clock.now += factory.request_seconds
                if factory.request_error is not None:
                    raise factory.request_error

            def getresponse(self):
                self.calls.append("getresponse")
                self.response = FakeResponse(factory.status, factory.chunks, factory.headers,
                                             factory.clock, factory.seconds_per_read)
                return self.response

            def close(self) -> None:
                self.closed = True

        self.conn = Conn()
        return self.conn

    def send(self, timeout: float = 30.0):
        return https_transport("POST", URL, {"Authorization": "Bearer " + FAKE_KEY}, b"{}",
                               timeout, connection_factory=self, clock=self.clock)


def _meta(factory: FakeConnectionFactory) -> MetaProvider:
    settings = load_settings({"DEALPILOT_AI_PROVIDER": "meta",
                              "DEALPILOT_META_API_KEY": FAKE_KEY,
                              "DEALPILOT_AI_TIMEOUT_SECONDS": "10"})

    def transport(method, url, headers, body, timeout):
        return https_transport(method, url, headers, body, timeout,
                               connection_factory=factory, clock=factory.clock)

    return MetaProvider(settings, transport=transport)


def _request() -> CompletionRequest:
    return CompletionRequest([Message("user", "Top region?")])


def _body(n: int) -> list[bytes]:
    data = (SECRET * (n // len(SECRET) + 1))[:n]
    return [data[i:i + 100_000] for i in range(0, n, 100_000)]


# --------------------------------------------------------------------------- AC-AI-14

def test_ac_ai_14_exactly_one_mib_is_accepted() -> None:
    factory = FakeConnectionFactory(chunks=_body(MAX_RESPONSE_BYTES),
                                    headers={"Content-Length": str(MAX_RESPONSE_BYTES)})
    status, body = factory.send()
    assert (status, len(body)) == (200, MAX_RESPONSE_BYTES)
    assert max(factory.conn.response.requested) <= READ_CHUNK == 64 * 1024
    assert factory.conn.closed


def test_ac_ai_14_one_mib_plus_one_byte_is_refused() -> None:
    factory = FakeConnectionFactory(chunks=_body(MAX_RESPONSE_BYTES + 1))  # no Content-Length
    with pytest.raises(ResponseTooLarge):
        factory.send()
    assert factory.conn.closed


def test_ac_ai_14_large_content_length_is_refused_before_reading() -> None:
    factory = FakeConnectionFactory(chunks=_body(10),
                                    headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)})
    with pytest.raises(ResponseTooLarge):
        factory.send()
    assert factory.conn.response.requested == []  # nothing was read
    assert factory.conn.closed


@pytest.mark.parametrize("status", [200, 401, 429, 500])
def test_ac_ai_14_limit_applies_to_every_body_through_meta(status: int) -> None:
    factory = FakeConnectionFactory(status=status, chunks=_body(MAX_RESPONSE_BYTES + 1))
    with pytest.raises(AIResponseError, match="response too large") as info:
        _meta(factory).complete(_request())
    message = str(info.value) + repr(info.value)
    for leaked in (FAKE_KEY, "internal secret", "Top region"):
        assert leaked not in message
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert factory.conn.closed


def test_ac_ai_14_injected_transport_is_limited_too() -> None:
    settings = load_settings({"DEALPILOT_AI_PROVIDER": "meta",
                              "DEALPILOT_META_API_KEY": FAKE_KEY})
    provider = MetaProvider(settings, transport=lambda *a: (200, b"x" * (MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(AIResponseError, match="too large"):
        provider.complete(_request())


def test_ac_ai_14_small_valid_response_unchanged() -> None:
    factory = FakeConnectionFactory()
    result = _meta(factory).complete(_request())
    assert result.text == "ok"
    assert factory.conn.closed


# --------------------------------------------------------------------------- AC-AI-15

def test_ac_ai_15_short_reads_that_pass_the_deadline_time_out() -> None:
    # 5 chunks, 3 s per read: every read is shorter than the 10 s timeout, the sum is not.
    factory = FakeConnectionFactory(chunks=[b"a"] * 5, seconds_per_read=3.0)
    with pytest.raises(TimeoutError):
        factory.send(timeout=10.0)
    assert factory.conn.closed
    assert len(factory.conn.response.requested) == 4  # stopped before the fifth read


def test_ac_ai_15_socket_gets_the_time_left() -> None:
    # 1 s connect, 1 s send, 2 s per read, 10 s deadline.
    factory = FakeConnectionFactory(chunks=[b"a", b"b"], seconds_per_read=2.0,
                                    request_seconds=1.0, connect_seconds=1.0)
    status, body = factory.send(timeout=10.0)
    assert (status, body) == (200, b"ab")
    assert factory.conn.timeout == 10.0  # connect gets the time left at the start
    # before send, before the response headers, then before each of the three reads
    assert factory.conn.sock.timeouts == [9.0, 8.0, 8.0, 6.0, 4.0]
    assert factory.conn.calls == ["connect", "request", "getresponse"]
    assert factory.conn.closed


def test_ac_ai_15_connect_is_separate_from_send() -> None:
    """The send never runs with the full initial timeout once connect used some time."""
    factory = FakeConnectionFactory(connect_seconds=7.0)
    factory.send(timeout=10.0)
    assert factory.conn.sock.timeouts[0] == 3.0  # 10 s budget - 7 s spent connecting


def test_ac_ai_15_slow_connect_times_out_before_sending() -> None:
    factory = FakeConnectionFactory(connect_seconds=10.0)
    with pytest.raises(TimeoutError):
        factory.send(timeout=10.0)
    assert factory.conn.calls == ["connect"]  # nothing was sent
    assert factory.conn.closed


def test_ac_ai_15_deadline_is_total_not_per_phase() -> None:
    # Each phase alone is well under 10 s; together they pass it.
    factory = FakeConnectionFactory(connect_seconds=4.0, request_seconds=4.0,
                                    chunks=[b"a"], seconds_per_read=4.0)
    with pytest.raises(TimeoutError):
        factory.send(timeout=10.0)
    assert factory.conn.calls == ["connect", "request", "getresponse"]
    assert factory.conn.closed


def test_ac_ai_15_slow_request_phase_times_out() -> None:
    factory = FakeConnectionFactory(request_seconds=10.0)
    with pytest.raises(TimeoutError):
        factory.send(timeout=10.0)
    assert factory.conn.response is None and factory.conn.closed
    assert factory.conn.calls == ["connect", "request"]  # no response read


def test_ac_ai_15_last_read_must_end_before_deadline() -> None:
    factory = FakeConnectionFactory(chunks=[b"a"], seconds_per_read=6.0)
    with pytest.raises(TimeoutError):
        factory.send(timeout=10.0)  # 6 s + 6 s for the empty end-of-body read


def test_ac_ai_15_meta_maps_deadline_to_timeout_error() -> None:
    factory = FakeConnectionFactory(chunks=[b"a"] * 5, seconds_per_read=3.0)
    with pytest.raises(AITimeoutError) as info:
        _meta(factory).complete(_request())
    assert FAKE_KEY not in str(info.value)
    assert factory.conn.closed


def test_ac_ai_15_connection_closed_on_network_error() -> None:
    factory = FakeConnectionFactory(request_error=ConnectionResetError("reset"))
    with pytest.raises(ConnectionResetError):
        factory.send()
    assert factory.conn.closed


def test_ac_ai_15_real_http_response_has_read1() -> None:
    """The default transport relies on HTTPResponse.read1 (standard library)."""
    assert hasattr(http.client.HTTPResponse, "read1")
