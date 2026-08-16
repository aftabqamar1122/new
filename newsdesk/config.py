"""Persistent user configuration.

Settings live in ``~/.newsdesk/config.json`` and are fully editable from the
Settings dialog in the app. API keys can also be supplied through the usual
environment variables, which take precedence only when the stored key is blank.
"""

from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path
from typing import Any

from .sources import DEFAULT_SOURCES

APP_DIR = Path(os.environ.get("NEWSDESK_HOME", Path.home() / ".newsdesk"))
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "newsdesk.log"
STATE_PATH = APP_DIR / "state.json"

ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "ai": {
        "provider": "anthropic",
        "enabled": True,
        "rank_with_ai": False,
        "providers": {
            "anthropic": {
                "api_key": "",
                "model": "claude-opus-5",
                "base_url": "",
                "max_tokens": 8000,
            },
            "openai": {
                "api_key": "",
                "model": "gpt-5.6",
                "base_url": "https://api.openai.com/v1",
                "max_tokens": 8000,
            },
            "gemini": {
                "api_key": "",
                "model": "gemini-3.5-flash",
                "base_url": "https://generativelanguage.googleapis.com/v1beta",
                "max_tokens": 8000,
            },
            "ollama": {
                "api_key": "",
                "model": "llama3.1",
                "base_url": "http://localhost:11434",
                "max_tokens": 8000,
            },
        },
    },
    "schedule": {
        "enabled": True,
        "times": ["07:00", "12:00", "18:00"],
        "run_on_start": False,
    },
    "collection": {
        "max_age_hours": 24,
        "max_articles": 120,
        "per_feed_limit": 40,
        "keep_other_category": False,
        "collapse_duplicates": True,
        "min_title_length": 15,
    },
    "network": {
        "timeout": 20,
        "retries": 2,
        "concurrency": 8,
        "verify_ssl": True,
        "proxy": "",
        "user_agent": (
            "Mozilla/5.0 (compatible; NewsDesk/1.0; +https://example.invalid/newsdesk)"
        ),
    },
    "export": {
        "directory": str(Path.home() / "NewsDesk" / "reports"),
        "auto_export": True,
        "formats": ["markdown", "html"],
    },
    "ui": {
        "minimize_to_tray": True,
        "start_minimized": False,
        "notify_on_complete": True,
    },
    "sources": copy.deepcopy(DEFAULT_SOURCES),
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge stored settings over defaults so new keys appear after upgrades."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Config:
    """Dot-path accessible configuration backed by a JSON file."""

    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None):
        self.path = path or CONFIG_PATH
        self.data = _deep_merge(DEFAULT_CONFIG, data or {})

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or CONFIG_PATH
        stored: dict[str, Any] = {}
        if path.exists():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # A corrupt file must not stop the app from starting.
                stored = {}
        return cls(stored, path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        try:
            # The file holds API keys: keep it owner-readable only.
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    # -- convenience -----------------------------------------------------

    def provider_name(self) -> str:
        return self.get("ai.provider", "anthropic")

    def provider_config(self, name: str | None = None) -> dict[str, Any]:
        name = name or self.provider_name()
        cfg = dict(self.get(f"ai.providers.{name}", {}) or {})
        if not cfg.get("api_key") and name in ENV_KEYS:
            cfg["api_key"] = os.environ.get(ENV_KEYS[name], "")
        return cfg

    def enabled_sources(self) -> list[dict[str, Any]]:
        return [s for s in self.get("sources", []) if s.get("enabled", True)]

    def export_dir(self) -> Path:
        return Path(os.path.expanduser(self.get("export.directory"))).resolve()
