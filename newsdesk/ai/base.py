"""Common interface every AI backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a completion."""


class AIProvider(ABC):
    #: Registry key, e.g. ``"anthropic"``.
    name: str = "base"
    #: Human-readable name shown in the UI.
    label: str = "Base"
    #: Whether an API key is required before the provider can be used.
    needs_key: bool = True

    def __init__(self, config: dict[str, Any], network: dict[str, Any]):
        self.config = config or {}
        self.network = network or {}

    # -- configuration ---------------------------------------------------

    @property
    def model(self) -> str:
        return (self.config.get("model") or "").strip()

    @property
    def api_key(self) -> str:
        return (self.config.get("api_key") or "").strip()

    @property
    def base_url(self) -> str:
        return (self.config.get("base_url") or "").strip()

    @property
    def max_tokens(self) -> int:
        try:
            return max(256, int(self.config.get("max_tokens", 8000)))
        except (TypeError, ValueError):
            return 8000

    def ready(self) -> tuple[bool, str]:
        """Return (usable, reason) so the UI can explain what is missing."""
        if not self.model:
            return False, f"No model configured for {self.label}."
        if self.needs_key and not self.api_key:
            return False, f"No API key configured for {self.label}."
        return True, ""

    # -- request helpers -------------------------------------------------

    @property
    def timeout(self) -> float:
        # Analysis calls are much slower than a feed fetch, so scale the budget.
        return max(60.0, float(self.network.get("timeout", 20)) * 6)

    def request_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "verify": bool(self.network.get("verify_ssl", True)),
        }
        proxy = (self.network.get("proxy") or "").strip()
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        return kwargs

    # -- the one operation providers must implement ----------------------

    @abstractmethod
    def complete(self, system: str, prompt: str) -> str:
        """Return the model's plain-text answer, or raise :class:`ProviderError`."""
