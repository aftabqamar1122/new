"""Anthropic Claude backend, built on the official ``anthropic`` SDK."""

from __future__ import annotations

from .base import AIProvider, ProviderError


class AnthropicProvider(AIProvider):
    name = "anthropic"
    label = "Anthropic (Claude)"

    def _client(self):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ProviderError(
                "The 'anthropic' package is not installed. Run: pip install anthropic"
            ) from exc

        kwargs: dict[str, object] = {"api_key": self.api_key, "timeout": self.timeout}
        if self.base_url:
            kwargs["base_url"] = self.base_url

        proxy = (self.network.get("proxy") or "").strip()
        verify = bool(self.network.get("verify_ssl", True))
        if proxy or not verify:
            from anthropic import DefaultHttpxClient

            http_kwargs: dict[str, object] = {"verify": verify}
            if proxy:
                http_kwargs["proxy"] = proxy
            kwargs["http_client"] = DefaultHttpxClient(**http_kwargs)

        return anthropic, anthropic.Anthropic(**kwargs)

    def complete(self, system: str, prompt: str) -> str:
        anthropic, client = self._client()
        try:
            # Note: temperature/top_p are rejected on current Claude models, and
            # thinking is adaptive by default — max_tokens covers both thinking
            # and the visible answer, so keep it generous.
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"Unknown Claude model '{self.model}': {exc}") from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Anthropic rejected the API key.") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Anthropic rate limit reached — try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"Could not reach the Anthropic API: {exc}") from exc

        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            category = getattr(detail, "category", None) or "unspecified"
            raise ProviderError(f"Claude declined this request ({category}).")

        text = "\n".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()

        if response.stop_reason == "max_tokens":
            text += "\n\n_(Summary truncated: raise the max tokens setting.)_"
        if not text:
            raise ProviderError("Claude returned an empty response.")
        return text
