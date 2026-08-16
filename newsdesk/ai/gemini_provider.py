"""Google Gemini backend (``generateContent`` REST endpoint)."""

from __future__ import annotations

from typing import Any

import requests

from .base import AIProvider, ProviderError


class GeminiProvider(AIProvider):
    name = "gemini"
    label = "Google (Gemini)"

    def complete(self, system: str, prompt: str) -> str:
        base = self.base_url or "https://generativelanguage.googleapis.com/v1beta"
        model = self.model
        if model.startswith("models/"):
            model = model.split("/", 1)[1]
        url = f"{base.rstrip('/')}/models/{model}:generateContent"

        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": self.max_tokens},
        }

        try:
            response = requests.post(
                url,
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                **self.request_kwargs(),
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach the Gemini API: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"Gemini API error {response.status_code}: {_error_detail(response)}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("Gemini returned a non-JSON response.") from exc

        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise ProviderError(f"Gemini blocked this request ({block}).")

        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError("Gemini returned no candidates.")

        candidate = candidates[0]
        parts = ((candidate.get("content") or {}).get("parts")) or []
        text = "\n".join(p["text"] for p in parts if isinstance(p.get("text"), str)).strip()

        finish = candidate.get("finishReason")
        if not text:
            raise ProviderError(f"Gemini returned an empty response (finish: {finish}).")
        if finish == "MAX_TOKENS":
            text += "\n\n_(Summary truncated: raise the max tokens setting.)_"
        return text


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
        error = body.get("error")
        if isinstance(error, dict):
            return error.get("message") or str(error)
        return str(error or body)[:400]
    except ValueError:
        return response.text[:400]
