"""LLM backends — DeepSeek (OpenAI-compatible) and Anthropic.

The agent speaks to one small interface, so switching providers is a matter of
which API key is in your environment. Tool schemas are written once, in
Anthropic's shape, and translated per backend.
"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "anthropic": "claude-sonnet-5",
}

ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

MAX_TOKENS = 4096


class MissingAPIKey(RuntimeError):
    """No usable provider credentials were found."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw_arguments: str = ""
    error: str = ""


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None


class Backend(ABC):
    """One model turn, plus the message bookkeeping that provider expects."""

    provider: str
    model: str

    @abstractmethod
    def run(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        on_text: Callable[[str], None] | None = None,
    ) -> Reply:
        """Send a turn and return the model's text and any tool calls."""

    @abstractmethod
    def assistant_message(self, reply: Reply) -> dict:
        """The assistant turn to append to history."""

    @abstractmethod
    def tool_result_messages(self, results: list[tuple[ToolCall, Any]]) -> list[dict]:
        """The turns carrying tool output back to the model."""


# --- DeepSeek ---------------------------------------------------------------


class DeepSeekBackend(Backend):
    """DeepSeek via the OpenAI SDK — same wire format, different base URL."""

    provider = "deepseek"

    def __init__(self, api_key: str, model: str = "", stream: bool = True, base_url: str = DEEPSEEK_BASE_URL):
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover - environment issue, not logic
            raise RuntimeError("The DeepSeek backend needs the openai package: pip install openai") from e

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model or DEFAULT_MODELS["deepseek"]
        self.stream = stream

    @staticmethod
    def translate_tools(tools: list[dict]) -> list[dict]:
        """Anthropic tool schemas → OpenAI function schemas."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
            for tool in tools
        ]

    @staticmethod
    def _to_tool_call(call_id: str, name: str, raw_args: str) -> ToolCall:
        try:
            parsed = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError as e:
            return ToolCall(call_id, name, {}, raw_args, f"Could not parse arguments as JSON: {e}")
        if not isinstance(parsed, dict):
            return ToolCall(call_id, name, {}, raw_args, "Arguments must be a JSON object.")
        return ToolCall(call_id, name, parsed, raw_args)

    def run(self, system, messages, tools, on_text=None) -> Reply:
        request = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "system", "content": system}] + messages,
            "tools": self.translate_tools(tools),
        }

        if on_text and self.stream:
            text, collected = self._run_streaming(request, on_text)
        else:
            text, collected = self._run_blocking(request, on_text)

        calls = [self._to_tool_call(c["id"], c["name"], c["args"]) for c in collected]
        return Reply(text=text, tool_calls=calls, raw=collected)

    def _run_streaming(self, request: dict, on_text: Callable[[str], None]) -> tuple[str, list[dict]]:
        """Reassemble text and tool calls, which arrive split across chunks."""
        parts: list[str] = []
        slots: dict[int, dict] = {}

        for chunk in self.client.chat.completions.create(stream=True, **request):
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                parts.append(delta.content)
                on_text(delta.content)
            for call in getattr(delta, "tool_calls", None) or []:
                slot = slots.setdefault(call.index, {"id": "", "name": "", "args": ""})
                if call.id:
                    slot["id"] = call.id
                function = getattr(call, "function", None)
                if function is not None:
                    if function.name:
                        slot["name"] += function.name
                    if function.arguments:
                        slot["args"] += function.arguments

        return "".join(parts), [slots[i] for i in sorted(slots)]

    def _run_blocking(self, request: dict, on_text: Callable[[str], None] | None) -> tuple[str, list[dict]]:
        message = self.client.chat.completions.create(**request).choices[0].message
        text = message.content or ""
        if on_text and text:
            on_text(text)
        collected = [
            {"id": c.id, "name": c.function.name, "args": c.function.arguments or ""}
            for c in (message.tool_calls or [])
        ]
        return text, collected

    def assistant_message(self, reply: Reply) -> dict:
        message: dict[str, Any] = {"role": "assistant", "content": reply.text}
        if reply.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    # Echo the model's own argument string back verbatim.
                    "function": {"name": call.name, "arguments": call.raw_arguments or "{}"},
                }
                for call in reply.tool_calls
            ]
        return message

    def tool_result_messages(self, results: list[tuple[ToolCall, Any]]) -> list[dict]:
        return [
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)}
            for call, result in results
        ]


# --- Anthropic --------------------------------------------------------------


class AnthropicBackend(Backend):
    provider = "anthropic"

    def __init__(self, api_key: str, model: str = "", stream: bool = True):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - environment issue, not logic
            raise RuntimeError("The Anthropic backend needs the anthropic package: pip install anthropic") from e

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model or DEFAULT_MODELS["anthropic"]
        self.stream = stream

    def run(self, system, messages, tools, on_text=None) -> Reply:
        request = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "tools": tools,
            "messages": messages,
        }

        if on_text and self.stream:
            with self.client.messages.stream(**request) as stream:
                for delta in stream.text_stream:
                    on_text(delta)
                message = stream.get_final_message()
        else:
            message = self.client.messages.create(**request)
            if on_text:
                for block in message.content:
                    if block.type == "text":
                        on_text(block.text)

        text = "\n".join(b.text for b in message.content if b.type == "text").strip()
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=b.input, raw_arguments=json.dumps(b.input, default=str))
            for b in message.content
            if b.type == "tool_use"
        ]
        return Reply(text=text, tool_calls=calls, raw=message)

    def assistant_message(self, reply: Reply) -> dict:
        return {"role": "assistant", "content": reply.raw.content}

    def tool_result_messages(self, results: list[tuple[ToolCall, Any]]) -> list[dict]:
        # Anthropic wants every result of a turn in one user message.
        return [{
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(result, default=str),
                }
                for call, result in results
            ],
        }]


# --- selection --------------------------------------------------------------


def detect_provider() -> str:
    """Pick a provider from whichever API key is set. DeepSeek wins a tie."""
    for provider in ("deepseek", "anthropic"):
        if os.environ.get(ENV_KEYS[provider]):
            return provider
    return ""


def build_backend(provider: str = "auto", model: str = "", api_key: str = "", stream: bool = True) -> Backend:
    """Construct the backend for `provider`, or whichever key is available."""
    if provider in ("", "auto"):
        provider = detect_provider()
        if not provider:
            raise MissingAPIKey(
                "No API key found. Set one of:\n"
                "  export DEEPSEEK_API_KEY=your_key_here     # https://platform.deepseek.com\n"
                "  export ANTHROPIC_API_KEY=your_key_here    # https://console.anthropic.com"
            )

    if provider not in ENV_KEYS:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {', '.join(ENV_KEYS)}")

    key = api_key or os.environ.get(ENV_KEYS[provider], "")
    if not key:
        raise MissingAPIKey(f"{ENV_KEYS[provider]} is not set.\n  export {ENV_KEYS[provider]}=your_key_here")

    model = model or os.environ.get(f"{provider.upper()}_MODEL", "")

    if provider == "deepseek":
        return DeepSeekBackend(api_key=key, model=model, stream=stream)
    return AnthropicBackend(api_key=key, model=model, stream=stream)
