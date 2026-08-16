"""OpenAI backend.

Uses the Responses API (``POST /v1/responses``) and transparently falls back to
Chat Completions for endpoints or gateways that only implement the older route.
Any OpenAI-compatible gateway works by changing the base URL.
"""

from __future__ import annotations

from typing import Any

import requests

from .base import AIProvider, ProviderError


class OpenAIProvider(AIProvider):
    name = "openai"
    label = "OpenAI (GPT)"

    def _url(self, path: str) -> str:
        base = self.base_url or "https://api.openai.com/v1"
        return f"{base.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def complete(self, system: str, prompt: str) -> str:
        style = (self.config.get("api_style") or "responses").lower()
        if style == "chat":
            return self._chat_completions(system, prompt)
        try:
            return self._responses(system, prompt)
        except ProviderError as exc:
            if "404" not in str(exc):
                raise
            # Older/self-hosted gateways only expose /chat/completions.
            return self._chat_completions(system, prompt)

    # -- Responses API ---------------------------------------------------

    def _responses(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "instructions": system,
            "input": prompt,
            "max_output_tokens": self.max_tokens,
        }
        data = self._post("/responses", payload)
        text = self._extract_responses_text(data)
        if not text:
            status = data.get("status")
            if status == "incomplete":
                reason = (data.get("incomplete_details") or {}).get("reason", "unknown")
                raise ProviderError(f"OpenAI response incomplete ({reason}).")
            raise ProviderError("OpenAI returned an empty response.")
        return text

    @staticmethod
    def _extract_responses_text(data: dict[str, Any]) -> str:
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            return data["output_text"].strip()
        chunks: list[str] = []
        for item in data.get("output", []) or []:
            if item.get("type") != "message":
                continue  # skip reasoning / tool items
            for block in item.get("content", []) or []:
                if block.get("type") in ("output_text", "text") and block.get("text"):
                    chunks.append(block["text"])
        return "\n".join(chunks).strip()

    # -- Chat Completions ------------------------------------------------

    def _chat_completions(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": self.max_tokens,
        }
        data = self._post("/chat/completions", payload)
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Unexpected OpenAI response shape: {data}") from exc
        if not text:
            raise ProviderError("OpenAI returned an empty response.")
        return text

    # -- transport -------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.post(
                self._url(path),
                headers=self._headers(),
                json=payload,
                **self.request_kwargs(),
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach OpenAI: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"OpenAI API error {response.status_code}: {_error_detail(response)}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("OpenAI returned a non-JSON response.") from exc


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
        error = body.get("error")
        if isinstance(error, dict):
            return error.get("message") or str(error)
        return str(error or body)[:400]
    except ValueError:
        return response.text[:400]
