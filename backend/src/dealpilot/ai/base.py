"""The common provider contract (spec 004 section 4.2)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from dealpilot.ai.config import AISettings
from dealpilot.ai.types import CompletionRequest, CompletionResult


class AIProvider(ABC):
    """One language-model backend. Subclasses set `name` and implement `complete`."""

    name: str = ""

    def __init__(self, settings: AISettings) -> None:
        self.settings = settings

    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Return the model's reply, or raise an `AIError` subclass."""
