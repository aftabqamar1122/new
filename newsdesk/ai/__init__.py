"""Pluggable AI providers used for the daily brief and optional re-ranking."""

from .base import AIProvider, ProviderError
from .registry import PROVIDER_LABELS, available_providers, get_provider

__all__ = [
    "AIProvider",
    "ProviderError",
    "PROVIDER_LABELS",
    "available_providers",
    "get_provider",
]
