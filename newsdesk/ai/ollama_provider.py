"""Local Ollama backend — keeps the whole pipeline offline and key-free."""

from __future__ import annotations

import requests

from .base import AIProvider, ProviderError


class OllamaProvider(AIProvider):
    name = "ollama"
    label = "Ollama (local)"
    needs_key = False

    def complete(self, system: str, prompt: str) -> str:
        base = self.base_url or "http://localhost:11434"
        url = f"{base.rstrip('/')}/api/chat"
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "options": {"num_predict": self.max_tokens},
        }

        kwargs = self.request_kwargs()
        kwargs.pop("proxies", None)  # a local daemon must not go through a proxy
        try:
            response = requests.post(url, json=payload, **kwargs)
        except requests.RequestException as exc:
            raise ProviderError(
                f"Could not reach Ollama at {base} — is 'ollama serve' running? ({exc})"
            ) from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"Ollama error {response.status_code}: {response.text[:400]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("Ollama returned a non-JSON response.") from exc

        text = ((data.get("message") or {}).get("content") or "").strip()
        if not text:
            raise ProviderError("Ollama returned an empty response.")
        return text
