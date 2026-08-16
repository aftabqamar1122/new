"""Prompt construction and AI post-processing of a collected batch."""

from __future__ import annotations

import json
import re
from typing import Callable

from .ai.base import AIProvider, ProviderError
from .analysis import grade
from .models import (
    CATEGORY_FINANCIAL,
    CATEGORY_MILITARY,
    Article,
    clean_text,
)

Logger = Callable[[str, str], None]

SYSTEM_PROMPT = (
    "You are a defence and markets desk analyst writing the daily brief for an "
    "informed reader who has not seen today's news. You work only from the "
    "headlines supplied to you: never add facts, figures, or events that are not "
    "in the input, and never speculate about outcomes. Where outlets disagree, "
    "say so. Attribute claims to the outlet in parentheses, e.g. (Reuters)."
)

BRIEF_INSTRUCTIONS = """Write the brief in Markdown with exactly these sections:

## Executive summary
Three to five sentences on what actually matters today, ordered by consequence.

## Military & security
Up to six bullets. Each bullet: the development, where it happened, why it matters.

## Markets & economy
Up to six bullets, same shape.

## Watchlist
Two to four short bullets on what to watch next, grounded only in the stories above.

Rules:
- Group related headlines into a single bullet instead of repeating a story.
- Prefer items marked HIGH importance; ignore low-value filler.
- Keep the whole brief under 500 words. No preamble, no closing commentary.
"""


def build_digest(articles: list[Article], limit: int = 70) -> str:
    """Compact, token-efficient rendering of the batch for the model."""
    lines: list[str] = []
    for index, article in enumerate(articles[:limit], start=1):
        summary = clean_text(article.summary, limit=180)
        corroboration = (
            f" | also: {', '.join(article.corroborating_sources[:3])}"
            if article.corroborating_sources
            else ""
        )
        lines.append(
            f"[{index}] {article.importance.upper()} | {article.category} | "
            f"{article.region} | {article.source} | {article.published_label()}"
            f"{corroboration}\n    {article.title}"
            + (f"\n    {summary}" if summary else "")
        )
    return "\n".join(lines)


def build_prompt(articles: list[Article]) -> str:
    military = sum(1 for a in articles if a.category == CATEGORY_MILITARY)
    financial = sum(1 for a in articles if a.category == CATEGORY_FINANCIAL)
    header = (
        f"Today's collected headlines: {len(articles)} stories "
        f"({military} military/security, {financial} financial/economic).\n\n"
    )
    return f"{header}{build_digest(articles)}\n\n{BRIEF_INSTRUCTIONS}"


def summarize(provider: AIProvider, articles: list[Article], log: Logger) -> str:
    """Ask the configured provider for the daily brief."""
    if not articles:
        return "_No qualifying stories were collected in this run._"

    usable, reason = provider.ready()
    if not usable:
        raise ProviderError(reason)

    log("info", f"Requesting brief from {provider.label} ({provider.model})…")
    text = provider.complete(SYSTEM_PROMPT, build_prompt(articles))
    log("info", f"Brief received ({len(text.split())} words)")
    return text.strip()


RANK_SYSTEM = (
    "You triage news for a defence and markets desk. You classify supplied "
    "headlines by consequence only, and reply with JSON and nothing else."
)

RANK_INSTRUCTIONS = """Classify each numbered headline above as high, medium, or low importance.

high   = materially changes the security or economic picture (armed escalation,
         central-bank or sovereign decisions, major sanctions, systemic market moves)
medium = notable development worth knowing, but not decisive
low    = routine coverage, commentary, or incremental updates

Reply with only this JSON object, using the bracketed numbers:
{"high": [1, 4], "medium": [2, 5], "low": [3]}
"""


def rerank(provider: AIProvider, articles: list[Article], log: Logger) -> int:
    """Optionally let the model adjust importance. Returns the number changed.

    Any failure here is non-fatal — the heuristic grades stay in place.
    """
    if not articles:
        return 0
    usable, reason = provider.ready()
    if not usable:
        raise ProviderError(reason)

    subset = articles[:70]
    prompt = f"{build_digest(subset)}\n\n{RANK_INSTRUCTIONS}"
    raw = provider.complete(RANK_SYSTEM, prompt)
    mapping = _parse_rank_json(raw)
    if not mapping:
        log("warn", "AI ranking response could not be parsed — keeping heuristic grades")
        return 0

    changed = 0
    for level, indices in mapping.items():
        for index in indices:
            position = index - 1
            if 0 <= position < len(subset) and subset[position].importance != level:
                subset[position].importance = level
                subset[position].reasons.append("AI re-ranked")
                changed += 1

    articles.sort(
        key=lambda a: (
            {"high": 0, "medium": 1, "low": 2}.get(a.importance, 3),
            -a.score,
        )
    )
    log("info", f"AI ranking adjusted {changed} of {len(subset)} stories")
    return changed


def _parse_rank_json(raw: str) -> dict[str, list[int]]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    out: dict[str, list[int]] = {}
    for level in ("high", "medium", "low"):
        values = data.get(level) or []
        if isinstance(values, list):
            out[level] = [int(v) for v in values if isinstance(v, (int, str)) and str(v).isdigit()]
    return out


def fallback_summary(articles: list[Article]) -> str:
    """Deterministic brief used when no provider is configured or the call fails."""
    if not articles:
        return "_No qualifying stories were collected in this run._"

    def section(title: str, items: list[Article]) -> str:
        if not items:
            return f"## {title}\n\n_Nothing of note._\n"
        lines = [f"## {title}\n"]
        for article in items[:6]:
            lines.append(
                f"- **{article.title}** — {article.source}, {article.region} "
                f"({article.importance})"
            )
        return "\n".join(lines) + "\n"

    high = [a for a in articles if a.importance == "high"]
    military = [a for a in articles if a.category == CATEGORY_MILITARY]
    financial = [a for a in articles if a.category == CATEGORY_FINANCIAL]
    regions = sorted({a.region for a in high or articles[:10]})

    head = (
        "## Executive summary\n\n"
        f"{len(articles)} stories collected — {len(high)} rated high importance, "
        f"{len(military)} military/security and {len(financial)} financial/economic. "
        f"Most active regions: {', '.join(regions[:4]) or 'Global'}. "
        "_(Generated without AI: heuristic ranking only.)_\n"
    )
    return "\n".join(
        [head, section("Military & security", military), section("Markets & economy", financial)]
    )


# Re-exported for callers that adjust scores and need the matching grade.
__all__ = [
    "SYSTEM_PROMPT",
    "build_digest",
    "build_prompt",
    "summarize",
    "rerank",
    "fallback_summary",
    "grade",
]
