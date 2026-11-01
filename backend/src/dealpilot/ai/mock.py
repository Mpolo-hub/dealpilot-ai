"""Offline mock provider (spec 004 section 4.4): no key, no network, no randomness."""
from __future__ import annotations

from dealpilot.ai.base import AIProvider
from dealpilot.ai.types import CompletionRequest, CompletionResult, Usage

ECHO_LIMIT = 200


class MockProvider(AIProvider):
    name = "mock"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        prompt = request.messages[-1].content
        text = f"[mock:{self.settings.model}] {prompt[:ECHO_LIMIT]}"
        usage = Usage(prompt_tokens=sum(len(m.content.split()) for m in request.messages),
                      completion_tokens=len(text.split()))
        return CompletionResult(text=text, provider=self.name, model=self.settings.model,
                                finish_reason="stop", usage=usage)
