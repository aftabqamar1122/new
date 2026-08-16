"""Provider lookup used by the pipeline and the Settings dialog."""

from __future__ import annotations

from typing import Any

from .anthropic_provider import AnthropicProvider
from .base import AIProvider
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider

_PROVIDERS: dict[str, type[AIProvider]] = {
    AnthropicProvider.name: AnthropicProvider,
    OpenAIProvider.name: OpenAIProvider,
    GeminiProvider.name: GeminiProvider,
    OllamaProvider.name: OllamaProvider,
}

PROVIDER_LABELS: dict[str, str] = {
    name: cls.label for name, cls in _PROVIDERS.items()
}
PROVIDER_LABELS["none"] = "No AI (headlines only)"


def available_providers() -> list[str]:
    return list(_PROVIDERS.keys()) + ["none"]


def get_provider(
    name: str, config: dict[str, Any], network: dict[str, Any]
) -> AIProvider | None:
    """Instantiate a provider, or return ``None`` when AI is switched off."""
    if name in ("none", "", None):
        return None
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise KeyError(f"Unknown AI provider: {name}")
    return cls(config, network)
