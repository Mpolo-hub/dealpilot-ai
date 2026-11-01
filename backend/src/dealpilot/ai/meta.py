"""Meta Model API adapter (spec 004 section 4.4).

The wire format follows assumptions A1 to A5 of spec 004, which are unverified until Q1 is
closed; they live only in this file. The transport is injectable so tests never open a
connection. The default transport uses the standard library with verified certificates.
"""
from __future__ import annotations

import http.client
import json
import ssl
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from dealpilot.ai.base import AIProvider
from dealpilot.ai.config import META_KEY_VAR, AISettings
from dealpilot.ai.errors import (
    AIAuthError,
    AIBillingError,
    AIConfigError,
    AIError,
    AIProviderError,
    AIRateLimitError,
    AIResponseError,
    AITimeoutError,
)
from dealpilot.ai.types import CompletionRequest, CompletionResult, Usage

# (method, url, headers, body, timeout_seconds) -> (status, response body)
Transport = Callable[[str, str, dict[str, str], bytes, float], tuple[int, bytes]]

COMPLETIONS_PATH = "/chat/completions"  # A2
MAX_RESPONSE_BYTES = 1024 * 1024  # D5: 1 MiB, error bodies included
READ_CHUNK = 64 * 1024
_STATUS_ERRORS: dict[int, tuple[type[AIError], str]] = {  # A5
    401: (AIAuthError, "the API key was rejected"),
    403: (AIAuthError, "the API key was rejected"),
    402: (AIBillingError, "billing or payment is required"),
    429: (AIRateLimitError, "rate limit reached"),
}


class ResponseTooLarge(Exception):
    """The response body is over MAX_RESPONSE_BYTES (spec 004 D5)."""


def https_transport(method: str, url: str, headers: dict[str, str], body: bytes,
                    timeout: float, *,
                    connection_factory: Callable[..., http.client.HTTPSConnection]
                    = http.client.HTTPSConnection,
                    clock: Callable[[], float] = time.monotonic) -> tuple[int, bytes]:
    """Send one HTTPS request with certificate checks (spec 004 sections 4.4 and 8).

    `timeout` is a total deadline for the whole request (D6), checked after every phase:
    - connect (TCP and TLS handshake) gets the time left at the start;
    - then the socket is set to the time still left before the request is sent, before
      the response headers are read, and before each body read;
    - the request stops with `TimeoutError` as soon as no time is left.
    Socket timeouts do not cover DNS resolution inside the standard library, so a slow
    name lookup can take longer than the deadline. Bodies, error bodies included, are
    capped at MAX_RESPONSE_BYTES (D5): a larger `Content-Length` is refused before reading,
    and the body is read in chunks of at most READ_CHUNK bytes. Raises `TimeoutError`,
    `OSError` or `ResponseTooLarge`; the connection is always closed.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("only https URLs are allowed")
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    deadline = clock() + timeout

    def remaining() -> float:
        left = deadline - clock()
        if left <= 0:
            raise TimeoutError("total request deadline passed")
        return left

    conn = connection_factory(parts.hostname, parts.port, timeout=remaining(),
                              context=ssl.create_default_context())
    try:
        conn.connect()  # TCP and TLS, so the send below gets only the time still left
        _set_socket_timeout(conn, remaining())
        conn.request(method, path, body=body, headers=headers)  # already connected: send only
        _set_socket_timeout(conn, remaining())
        response = conn.getresponse()
        length = response.getheader("Content-Length")
        if length is not None and length.strip().isdigit() \
                and int(length) > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge
        chunks: list[bytes] = []
        size = 0
        while True:
            _set_socket_timeout(conn, remaining())
            # read1 returns after at most one socket read, so the deadline is checked
            # between reads even when the server sends a few bytes at a time.
            chunk = response.read1(min(READ_CHUNK, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge
            chunks.append(chunk)
        remaining()  # the last read must also end before the deadline
        return response.status, b"".join(chunks)
    finally:
        conn.close()


def _set_socket_timeout(conn: http.client.HTTPSConnection, seconds: float) -> None:
    if conn.sock is not None:
        conn.sock.settimeout(seconds)


class MetaProvider(AIProvider):
    name = "meta"

    def __init__(self, settings: AISettings, transport: Transport | None = None) -> None:
        if settings.meta_api_key is None:
            raise AIConfigError(f"{META_KEY_VAR} is not set", provider=self.name)
        super().__init__(settings)
        self._transport = transport or https_transport

    def complete(self, request: CompletionRequest) -> CompletionResult:
        payload = {
            "model": self.settings.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.meta_api_key.reveal()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = self.settings.meta_base_url + COMPLETIONS_PATH
        body = json.dumps(payload).encode("utf-8")
        try:
            status, raw = self._transport("POST", url, headers, body,
                                          self.settings.timeout_seconds)
        except TimeoutError:
            raise AITimeoutError("the request timed out", provider=self.name) from None
        except ResponseTooLarge:
            raise AIResponseError("invalid response: response too large",
                                  provider=self.name) from None
        except (OSError, http.client.HTTPException):
            # `from None` keeps the low-level exception (which may hold the URL) out of
            # chained tracebacks.
            raise AIProviderError("the API could not be reached", provider=self.name) from None
        if len(raw) > MAX_RESPONSE_BYTES:  # D5 also for injected transports
            raise AIResponseError("invalid response: response too large", provider=self.name)
        if not 200 <= status < 300:
            error, reason = _STATUS_ERRORS.get(status, (AIProviderError, "request failed"))
            raise error(f"Meta API error {status}: {reason}", provider=self.name, status=status)
        return self._parse(raw)

    def _parse(self, raw: bytes) -> CompletionResult:
        """Validate a success body against A3."""
        def bad(what: str) -> AIResponseError:
            return AIResponseError(f"invalid response: {what}", provider=self.name)

        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise bad("not JSON") from None
        if not isinstance(data, dict):
            raise bad("not a JSON object")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise bad("no choices")
        message = choices[0].get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise bad("message content is not a string")
        finish = choices[0].get("finish_reason")
        if finish is not None and not isinstance(finish, str):
            raise bad("finish_reason is not a string")
        model = data.get("model", self.settings.model)
        if not isinstance(model, str):
            raise bad("model is not a string")
        return CompletionResult(text=text, provider=self.name, model=model,
                                finish_reason=finish, usage=self._usage(data.get("usage")))

    def _usage(self, usage: object) -> Usage | None:
        if usage is None:
            return None
        counts = [usage.get(k) if isinstance(usage, dict) else None
                  for k in ("prompt_tokens", "completion_tokens")]
        if not all(isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in counts):
            raise AIResponseError("invalid response: usage counts are not integers",
                                  provider=self.name)
        return Usage(prompt_tokens=counts[0], completion_tokens=counts[1])
