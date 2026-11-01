"""Provider registry (spec 004 section 4.4).

To add a provider: write an `AIProvider` subclass and add it to `REGISTRY` (and its name to
`config.PROVIDERS`). Code that calls `get_provider` does not change.
"""
from __future__ import annotations

from dealpilot.ai.base import AIProvider
from dealpilot.ai.config import AISettings, load_settings
from dealpilot.ai.errors import AIConfigError
from dealpilot.ai.gemini import GeminiProvider
from dealpilot.ai.meta import MetaProvider
from dealpilot.ai.mock import MockProvider

REGISTRY: dict[str, type[AIProvider]] = {
    MockProvider.name: MockProvider,
    MetaProvider.name: MetaProvider,
    GeminiProvider.name: GeminiProvider,
}


def get_provider(settings: AISettings | None = None) -> AIProvider:
    """Return the configured provider (default settings: from the environment)."""
    settings = load_settings() if settings is None else settings
    provider_class = REGISTRY.get(settings.provider)
    if provider_class is None:
        raise AIConfigError(f"unknown AI provider: {settings.provider}")
    return provider_class(settings)
