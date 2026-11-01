"""Google Gemini adapter, `generateContent` REST API (spec 006).

The HTTPS transport is the one in `meta.py` (D12): it is reused, not moved or copied. Every
paid call goes through the usage ledger (`budget.py`): phase 1 reserves before the network
call, phase 3 reconciles after it. The transport is called at most once per request (D6).
"""
from __future__ import annotations

import http.client
import json
import re

from dealpilot.ai.base import AIProvider
from dealpilot.ai.budget import Ledger, Outcome, Prices
from dealpilot.ai.config import (
    GEMINI_DATA_CLASS_VAR,
    GEMINI_KEY_VAR,
    GEMINI_MODEL_VAR,
    GEMINI_MODELS,
    GEMINI_PRICE_INPUT_VAR,
    GEMINI_PRICE_OUTPUT_VAR,
    GEMINI_PRICES_DATE_VAR,
    USAGE_DIR_VAR,
    AISettings,
)
from dealpilot.ai.errors import (
    AIAuthError,
    AIBillingError,
    AIBlockedError,
    AIConfigError,
    AIError,
    AIProviderError,
    AIRateLimitError,
    AIRequestError,
    AIResponseError,
    AITimeoutError,
)
from dealpilot.ai.meta import MAX_RESPONSE_BYTES, ResponseTooLarge, Transport, https_transport
from dealpilot.ai.types import CompletionRequest, CompletionResult, Usage

GENERATE_PATH = "/models/{model}:generateContent"  # F1
BLOCKED_FINISH_REASONS = ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII")
_REASON_CODE = re.compile(r"[A-Z0-9_]{1,64}")
_STATUS_ERRORS: dict[int, tuple[type[AIError], str]] = {  # section 6, D7
    400: (AIProviderError, "request failed"),
    401: (AIAuthError, "the API key was rejected or lacks permission"),
    402: (AIBillingError, "prepaid balance used up"),
    403: (AIAuthError, "the API key was rejected or lacks permission"),
    404: (AIConfigError, "model not found"),
    429: (AIRateLimitError, "rate limit reached"),
}


class _Reply(Exception):
    """Internal: carries the section 6 result of a received response."""


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, settings: AISettings, transport: Transport | None = None,
                 ledger: Ledger | None = None) -> None:
        required = (
            (settings.gemini_api_key, GEMINI_KEY_VAR),
            (settings.gemini_model, GEMINI_MODEL_VAR),
            (settings.gemini_data_class, GEMINI_DATA_CLASS_VAR),
            (settings.gemini_price_input, GEMINI_PRICE_INPUT_VAR),
            (settings.gemini_price_output, GEMINI_PRICE_OUTPUT_VAR),
            (settings.gemini_prices_checked_on, GEMINI_PRICES_DATE_VAR),
            (settings.usage_dir, USAGE_DIR_VAR),
        )
        for value, var in required:
            if value is None:
                raise AIConfigError(f"{var} is not set", provider=self.name)
        if settings.gemini_model not in GEMINI_MODELS:
            raise AIConfigError(f"{GEMINI_MODEL_VAR} must be one of {', '.join(GEMINI_MODELS)}",
                                provider=self.name)
        super().__init__(settings)
        self._transport = transport or https_transport
        self._ledger = ledger or Ledger(settings.usage_dir)
        self._prices = Prices(settings.gemini_price_input, settings.gemini_price_output,
                              settings.gemini_prices_checked_on)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        # Everything below up to `reserve` runs before any ledger read or network call.
        payload = self._payload(request)
        input_chars, input_bytes = self._check_limits(request)
        body = json.dumps(payload).encode("utf-8")
        reservation = self._ledger.reserve(
            provider=self.name, model=self.settings.gemini_model, input_chars=input_chars,
            input_bytes=input_bytes, max_output_tokens=request.max_tokens, prices=self._prices,
            budget_usd=self.settings.monthly_budget_usd,
            max_calls_per_hour=self.settings.max_calls_per_hour)

        result: CompletionResult | None = None
        error: AIError | None = None
        outcome = Outcome("kept")  # the request may have been sent from here on
        try:
            status, raw = self._transport("POST", self._url(), self._headers(), body,
                                          self.settings.timeout_seconds)
        except TimeoutError:
            error = AITimeoutError("the request timed out", provider=self.name)
        except ResponseTooLarge:
            error = AIResponseError("invalid response: response too large", provider=self.name)
        except (OSError, http.client.HTTPException):
            error = AIProviderError("the API could not be reached", provider=self.name)
        except BaseException:
            self._ledger.finish(reservation, outcome)
            raise
        else:
            outcome, result, error = self._read(status, raw)
        # Phase 3 never raises: if it can't write, the entry stays `reserved` (D17) and the
        # result already received is still returned as section 6 classifies it.
        self._ledger.finish(reservation, outcome)
        if error is not None:
            raise error from None
        return result

    # ----------------------------------------------------------------- request

    def _url(self) -> str:
        return self.settings.gemini_base_url + GENERATE_PATH.format(
            model=self.settings.gemini_model)

    def _headers(self) -> dict[str, str]:
        # The key goes only in this header, never in the URL (section 8).
        return {"x-goog-api-key": self.settings.gemini_api_key.reveal(),
                "Content-Type": "application/json"}

    def _payload(self, request: CompletionRequest) -> dict:
        """Section 4 and D9: system parts first, then alternating user and model items."""
        system: list[dict] = []
        contents: list[dict] = []
        for message in request.messages:
            if message.role == "system":
                if contents:
                    raise AIRequestError("system messages must come before the conversation",
                                         provider=self.name)
                system.append({"text": message.content})
                continue
            role = "model" if message.role == "assistant" else "user"
            if not contents and role == "model":
                raise AIRequestError("the conversation must start with a user message",
                                     provider=self.name)
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].append({"text": message.content})  # D9: one part each
            else:
                contents.append({"role": role, "parts": [{"text": message.content}]})
        payload: dict = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": request.max_tokens,
                                 "temperature": request.temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": system}
        return payload

    def _check_limits(self, request: CompletionRequest) -> tuple[int, int]:
        """Section 7.1 (D4, D14) and the D11 input estimate; nothing is ever cut."""
        input_chars = sum(len(m.content) for m in request.messages)
        if input_chars > self.settings.max_input_chars:
            raise AIRequestError(f"input is over {self.settings.max_input_chars} characters",
                                 provider=self.name)
        if request.max_tokens > self.settings.max_output_tokens:
            raise AIRequestError(f"max_tokens is over {self.settings.max_output_tokens}",
                                 provider=self.name)
        try:
            input_bytes = sum(len(m.content.encode("utf-8")) for m in request.messages)
        except UnicodeEncodeError:  # a lone surrogate has no UTF-8 form (D14)
            raise AIRequestError("a message holds a lone surrogate character",
                                 provider=self.name) from None
        return input_chars, input_bytes

    # ----------------------------------------------------------------- response

    def _read(self, status: int, raw: bytes
              ) -> tuple[Outcome, CompletionResult | None, AIError | None]:
        if len(raw) > MAX_RESPONSE_BYTES:  # spec 004 D5, also for injected transports
            return Outcome("kept"), None, AIResponseError(
                "invalid response: response too large", provider=self.name)
        if not 200 <= status < 300:
            return self._read_error(status, raw)
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return Outcome("kept"), None, self._bad("not JSON")
        if not isinstance(data, dict):
            return Outcome("kept"), None, self._bad("not a JSON object")
        try:
            usage = _usage(data)
        except ValueError:
            usage, bad_usage = None, True
        else:
            bad_usage = False
        outcome = Outcome("settled", *usage) if usage else Outcome("kept")
        try:
            result = self._classify(data, usage, bad_usage)
        except _Reply as reply:
            return outcome, None, reply.args[0]
        return outcome, result, None

    def _read_error(self, status: int, raw: bytes
                    ) -> tuple[Outcome, None, AIError]:
        outcome = Outcome("kept")
        if status in (400, 500):  # F9: only these two, and only with valid usage
            try:
                data = json.loads(raw)
                usage = _usage(data) if isinstance(data, dict) else None
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                usage = None
            if usage:
                outcome = Outcome("not_billed", *usage)
        error_class, text = _STATUS_ERRORS.get(status, (AIProviderError, "request failed"))
        # D18: `error.code` is documented as an integer (F5), which never meets the section
        # 6 rule for `reason`, so `reason` stays None and the status alone classifies it.
        return outcome, None, error_class(f"Gemini API error {status}: {text}",
                                          provider=self.name, status=status)

    def _classify(self, data: dict, usage: tuple[int, int, int] | None,
                  bad_usage: bool) -> CompletionResult:
        """Section 6 for a 2xx body. Raises `_Reply` with the error to give the caller.

        Invalid usage is checked first (user decision 2026-10-31): a blocked prompt with
        invalid usage gives `AIResponseError`, not `AIBlockedError`.
        """
        if bad_usage:
            raise _Reply(self._bad("usage counts are not valid"))
        feedback = data.get("promptFeedback")
        block = feedback.get("blockReason") if isinstance(feedback, dict) else None
        if block:
            raise _Reply(self._blocked(block))
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates \
                or not isinstance(candidates[0], dict):
            raise _Reply(self._bad("no candidates"))
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish in BLOCKED_FINISH_REASONS:
            raise _Reply(self._blocked(finish))
        text = self._text(candidate)
        if finish == "CONTINUATION":
            raise _Reply(self._bad("partial answer"))
        if finish not in ("STOP", "MAX_TOKENS"):
            raise _Reply(self._bad("unexpected finish reason"))
        if not text.strip():
            raise _Reply(self._bad("empty reply"))
        return CompletionResult(
            text=text, provider=self.name, model=self.settings.gemini_model,
            finish_reason="stop" if finish == "STOP" else "length",
            usage=Usage(usage[0], usage[1] + usage[2]) if usage else None)

    def _text(self, candidate: dict) -> str:
        """Non-thought text parts in order (D16: only `thought` true is skipped)."""
        content = candidate.get("content")
        if content is None:
            return ""
        parts = content.get("parts", []) if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise _Reply(self._bad("content has no parts list"))
        texts = []
        for part in parts:
            if not isinstance(part, dict):
                raise _Reply(self._bad("a part is not an object"))
            thought = part.get("thought", False)
            if not isinstance(thought, bool):
                raise _Reply(self._bad("a thought marker is not a boolean"))
            if "text" not in part or thought:
                continue
            if not isinstance(part["text"], str):
                raise _Reply(self._bad("a text part is not a string"))
            texts.append(part["text"])
        return "".join(texts)

    def _blocked(self, code: object) -> AIBlockedError:
        reason = code if isinstance(code, str) and _REASON_CODE.fullmatch(code) else None
        return AIBlockedError("content blocked by the provider", provider=self.name,
                              reason=reason)

    def _bad(self, what: str) -> AIResponseError:
        return AIResponseError(f"invalid response: {what}", provider=self.name)


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _usage(data: dict) -> tuple[int, int, int] | None:
    """`usageMetadata` as (prompt, candidates, thoughts); None if absent, ValueError if bad."""
    if "usageMetadata" not in data:
        return None
    meta = data["usageMetadata"]
    meta = meta if isinstance(meta, dict) else {}
    prompt = meta.get("promptTokenCount")
    output = meta.get("candidatesTokenCount")
    thoughts = meta.get("thoughtsTokenCount", 0)  # 0 when absent (section 4)
    if not (_is_count(prompt) and _is_count(output) and _is_count(thoughts)):
        raise ValueError("bad usage counts")
    return prompt, output, thoughts
