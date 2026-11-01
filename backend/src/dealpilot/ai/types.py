"""Provider-independent request and result types (spec 004 section 4.2).

Business code builds a `CompletionRequest` and reads a `CompletionResult`; it never sees a
provider's wire format.
"""
from __future__ import annotations

from dataclasses import dataclass

from dealpilot.ai.errors import AIRequestError

ROLES = ("system", "user", "assistant")
MAX_TOKENS_RANGE = (1, 4096)
TEMPERATURE_RANGE = (0.0, 2.0)


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise AIRequestError(f"role must be one of {', '.join(ROLES)}")
        if not isinstance(self.content, str) or not self.content.strip():
            raise AIRequestError("content must be a non-empty string")


@dataclass(frozen=True)
class CompletionRequest:
    messages: tuple[Message, ...]
    max_tokens: int = 512
    temperature: float = 0.0

    def __post_init__(self) -> None:
        # Accept any sequence but store a tuple, so the request stays immutable.
        if isinstance(self.messages, str | bytes):
            raise AIRequestError("messages must be a list of Message objects")
        try:
            object.__setattr__(self, "messages", tuple(self.messages))
        except TypeError:
            raise AIRequestError("messages must be a list of Message objects") from None
        if not self.messages:
            raise AIRequestError("messages must not be empty")
        if not all(isinstance(m, Message) for m in self.messages):
            raise AIRequestError("messages must be Message objects")
        if self.messages[-1].role != "user":
            raise AIRequestError("the last message must come from the user")
        low, high = MAX_TOKENS_RANGE
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) \
                or not low <= self.max_tokens <= high:
            raise AIRequestError(f"max_tokens must be an integer from {low} to {high}")
        low_t, high_t = TEMPERATURE_RANGE
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, int | float) \
                or not low_t <= self.temperature <= high_t:
            raise AIRequestError(f"temperature must be a number from {low_t} to {high_t}")


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: Usage | None = None
