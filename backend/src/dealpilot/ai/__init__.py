"""AI provider layer (specs 004 and 006): one interface over a mock, Meta and Gemini."""
from dealpilot.ai.base import AIProvider
from dealpilot.ai.config import AISettings, load_settings
from dealpilot.ai.errors import (
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
    AITimeoutError,
)
from dealpilot.ai.factory import get_provider
from dealpilot.ai.types import CompletionRequest, CompletionResult, Message, Usage

__all__ = [
    "AIAuthError", "AIBillingError", "AIBlockedError", "AIBudgetError", "AIConfigError",
    "AIError", "AIProvider", "AIProviderError", "AIRateLimitError", "AIRequestError",
    "AIResponseError", "AISettings", "AITimeoutError", "CompletionRequest", "CompletionResult",
    "Message", "Usage", "get_provider", "load_settings",
]
