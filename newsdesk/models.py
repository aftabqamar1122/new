"""Core data structures shared by the collector, analyzer, exporters and UI."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

CATEGORY_MILITARY = "military"
CATEGORY_FINANCIAL = "financial"
CATEGORY_OTHER = "other"

IMPORTANCE_HIGH = "high"
IMPORTANCE_MEDIUM = "medium"
IMPORTANCE_LOW = "low"

IMPORTANCE_ORDER = {IMPORTANCE_HIGH: 0, IMPORTANCE_MEDIUM: 1, IMPORTANCE_LOW: 2}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(value: str | None, limit: int = 0) -> str:
    """Strip HTML tags and collapse whitespace from feed-supplied text."""
    if not value:
        return ""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", value)).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


@dataclass
class Article:
    title: str
    link: str
    source: str
    feed_name: str
    summary: str = ""
    published: datetime | None = None
    category: str = CATEGORY_OTHER
    region: str = "Global"
    importance: str = IMPORTANCE_LOW
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    cluster_id: int = -1
    corroborating_sources: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        """Stable identity used for de-duplication across runs."""
        basis = (self.link or "").strip().lower() or normalize_title(self.title)
        return hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:16]

    @property
    def age_hours(self) -> float:
        if not self.published:
            return float("inf")
        delta = datetime.now(timezone.utc) - self.published
        return delta.total_seconds() / 3600.0

    def published_label(self) -> str:
        if not self.published:
            return "unknown"
        return self.published.astimezone().strftime("%Y-%m-%d %H:%M")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published"] = self.published.isoformat() if self.published else None
        data["uid"] = self.uid
        return data


@dataclass
class Report:
    generated_at: datetime
    articles: list[Article] = field(default_factory=list)
    ai_summary: str = ""
    ai_provider: str = "none"
    ai_model: str = ""
    errors: list[str] = field(default_factory=list)
    feeds_ok: int = 0
    feeds_failed: int = 0
    raw_count: int = 0
    files: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {
            "total": len(self.articles),
            IMPORTANCE_HIGH: 0,
            IMPORTANCE_MEDIUM: 0,
            IMPORTANCE_LOW: 0,
            CATEGORY_MILITARY: 0,
            CATEGORY_FINANCIAL: 0,
        }
        for article in self.articles:
            out[article.importance] = out.get(article.importance, 0) + 1
            out[article.category] = out.get(article.category, 0) + 1
        return out

    def by_category(self, category: str) -> list[Article]:
        return [a for a in self.articles if a.category == category]

    def slug(self) -> str:
        return self.generated_at.astimezone().strftime("%Y-%m-%d_%H%M")

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "articles": [a.to_dict() for a in self.articles],
            "ai_summary": self.ai_summary,
            "ai_provider": self.ai_provider,
            "ai_model": self.ai_model,
            "errors": self.errors,
            "feeds_ok": self.feeds_ok,
            "feeds_failed": self.feeds_failed,
            "raw_count": self.raw_count,
            "files": self.files,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Report":
        report = cls(generated_at=_parse_iso(data.get("generated_at")))
        for item in data.get("articles", []) or []:
            item = dict(item)
            item.pop("uid", None)
            item["published"] = _parse_iso(item.get("published"), allow_none=True)
            known = {f for f in Article.__dataclass_fields__}  # noqa: SLF001
            report.articles.append(Article(**{k: v for k, v in item.items() if k in known}))
        report.ai_summary = data.get("ai_summary", "")
        report.ai_provider = data.get("ai_provider", "none")
        report.ai_model = data.get("ai_model", "")
        report.errors = list(data.get("errors", []) or [])
        report.feeds_ok = int(data.get("feeds_ok", 0))
        report.feeds_failed = int(data.get("feeds_failed", 0))
        report.raw_count = int(data.get("raw_count", 0))
        report.files = list(data.get("files", []) or [])
        return report

    def title(self) -> str:
        return self.generated_at.astimezone().strftime(
            "Military & Financial Brief — %A, %d %B %Y %H:%M"
        )


def _parse_iso(value: str | None, allow_none: bool = False) -> datetime | None:
    if not value:
        return None if allow_none else datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None if allow_none else datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_STOPWORDS = {
    "about", "after", "against", "amid", "another", "around", "banks", "been",
    "before", "being", "between", "could", "during", "first", "from", "have",
    "into", "more", "most", "over", "said", "says", "should", "since", "than",
    "that", "their", "them", "there", "these", "they", "this", "those",
    "three", "through", "under", "until", "what", "when", "where", "which",
    "while", "will", "with", "would", "year", "years", "your",
}


def normalize_title(title: str) -> str:
    return _WS_RE.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())).strip()


def title_tokens(title: str) -> set[str]:
    """Significant tokens of a headline, used for cross-source story matching."""
    return {
        token
        for token in normalize_title(title).split()
        if len(token) > 3 and token not in _STOPWORDS
    }
