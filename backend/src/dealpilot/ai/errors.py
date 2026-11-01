"""Errors of the AI provider layer (spec 004 section 4.5).

Messages never contain the API key, the request body or the raw response body.
"""
from __future__ import annotations


class AIError(Exception):
    """Base class. `provider` names the provider; `status` is the HTTP status, if any.

    `reason` is an optional short code (spec 006 D19), such as a block reason. It never
    holds the key, the request, the response body or other confidential text.
    """

    def __init__(self, message: str, *, provider: str | None = None,
                 status: int | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.reason = reason


class AIConfigError(AIError):
    """Unknown provider or model, bad timeout or base URL, missing or malformed key."""


class AIRequestError(AIError):
    """Invalid `Message` or `CompletionRequest`."""


class AIAuthError(AIError):
    """The provider rejected the API key (HTTP 401 or 403)."""


class AIBillingError(AIError):
    """Billing or payment problem (HTTP 402)."""


class AIRateLimitError(AIError):
    """Rate limit reached (HTTP 429)."""


class AIProviderError(AIError):
    """Any other non-2xx status, or a network error."""


class AITimeoutError(AIError):
    """The request timed out."""


class AIResponseError(AIError):
    """The response body is not JSON or does not have the expected shape."""


class AIBlockedError(AIError):
    """The provider blocked the content (spec 006 section 6); `reason` holds the code."""


class AIBudgetError(AIError):
    """Local budget, call limit, usage ledger or lock problem (spec 006 section 7)."""
