"""Feed registry and concurrent RSS/Atom collection.

Reuters, Bloomberg and AP no longer publish open RSS endpoints, so those
publishers are followed through Google News search feeds scoped to their
domain. Every entry here is editable from Settings → Sources.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import feedparser
import requests

from .models import Article, clean_text, normalize_title

Logger = Callable[[str, str], None]


def _gnews(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + query.replace(" ", "+")
        + "&hl=en-US&gl=US&ceid=US:en"
    )


# category is a *hint* used by the classifier, not a hard label.
DEFAULT_SOURCES: list[dict[str, Any]] = [
    # --- General wires / world desks ---------------------------------
    {"name": "BBC World", "source": "BBC", "category": "mixed", "enabled": True,
     "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "BBC Business", "source": "BBC", "category": "financial", "enabled": True,
     "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    {"name": "Reuters World", "source": "Reuters", "category": "mixed", "enabled": True,
     "url": _gnews("when:1d allinurl:reuters.com/world")},
    {"name": "Reuters Business", "source": "Reuters", "category": "financial", "enabled": True,
     "url": _gnews("when:1d allinurl:reuters.com/business")},
    {"name": "Reuters Markets", "source": "Reuters", "category": "financial", "enabled": True,
     "url": _gnews("when:1d allinurl:reuters.com/markets")},
    {"name": "CNN World", "source": "CNN", "category": "mixed", "enabled": True,
     "url": "https://rss.cnn.com/rss/edition_world.rss"},
    {"name": "CNN Business", "source": "CNN", "category": "financial", "enabled": True,
     "url": "https://rss.cnn.com/rss/money_news_international.rss"},
    {"name": "NYT World", "source": "New York Times", "category": "mixed", "enabled": True,
     "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"},
    {"name": "NYT Business", "source": "New York Times", "category": "financial", "enabled": True,
     "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"},
    {"name": "NYT Economy", "source": "New York Times", "category": "financial", "enabled": True,
     "url": "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"},
    {"name": "AP Top News", "source": "Associated Press", "category": "mixed", "enabled": True,
     "url": _gnews("when:1d allinurl:apnews.com")},
    {"name": "Al Jazeera", "source": "Al Jazeera", "category": "mixed", "enabled": True,
     "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Guardian World", "source": "The Guardian", "category": "mixed", "enabled": True,
     "url": "https://www.theguardian.com/world/rss"},
    # --- Financial desks ---------------------------------------------
    {"name": "CNBC Top News", "source": "CNBC", "category": "financial", "enabled": True,
     "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "CNBC Finance", "source": "CNBC", "category": "financial", "enabled": True,
     "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
    {"name": "CNBC Economy", "source": "CNBC", "category": "financial", "enabled": True,
     "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html"},
    {"name": "MarketWatch Top Stories", "source": "MarketWatch", "category": "financial",
     "enabled": True,
     "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"name": "Financial Times", "source": "Financial Times", "category": "financial",
     "enabled": True, "url": "https://www.ft.com/rss/home"},
    {"name": "Bloomberg", "source": "Bloomberg", "category": "financial", "enabled": True,
     "url": _gnews("when:1d allinurl:bloomberg.com")},
    {"name": "Federal Reserve Press", "source": "Federal Reserve", "category": "financial",
     "enabled": True,
     "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    # --- Defence / security desks ------------------------------------
    {"name": "Defense News", "source": "Defense News", "category": "military", "enabled": True,
     "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "Breaking Defense", "source": "Breaking Defense", "category": "military",
     "enabled": True, "url": "https://breakingdefense.com/feed/"},
    {"name": "Military Times", "source": "Military Times", "category": "military",
     "enabled": True,
     "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "US DoD Releases", "source": "US Dept. of Defense", "category": "military",
     "enabled": True,
     "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=20"},
    {"name": "Reuters Defence", "source": "Reuters", "category": "military", "enabled": True,
     "url": _gnews("when:1d allinurl:reuters.com (defence OR military OR strike)")},
]

# Google News wraps headlines as "Real headline - Publisher".
_GNEWS_SUFFIX = re.compile(r"\s+-\s+[^-]{2,40}$")


def _parse_date(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, key, None) or (
            entry.get(key) if isinstance(entry, dict) else None
        )
        if parsed:
            try:
                return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _entry_link(entry: Any) -> str:
    link = (entry.get("link") or "").strip()
    if link:
        return link
    for candidate in entry.get("links", []) or []:
        if candidate.get("href"):
            return candidate["href"]
    return ""


def build_session(net: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": net.get("user_agent") or "NewsDesk/1.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        }
    )
    proxy = (net.get("proxy") or "").strip()
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    session.verify = bool(net.get("verify_ssl", True))
    return session


def fetch_feed(
    session: requests.Session,
    source: dict[str, Any],
    net: dict[str, Any],
    per_feed_limit: int,
) -> tuple[list[Article], str | None]:
    """Fetch and parse one feed. Returns (articles, error_message)."""
    url = source.get("url", "")
    timeout = float(net.get("timeout", 20))
    retries = max(0, int(net.get("retries", 2)))
    last_error: str | None = None

    for attempt in range(retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(f"unparseable feed ({parsed.bozo_exception})")
            return _entries_to_articles(parsed.entries, source, per_feed_limit), None
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop a run
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))

    return [], last_error


def _entries_to_articles(
    entries: Iterable[Any], source: dict[str, Any], per_feed_limit: int
) -> list[Article]:
    articles: list[Article] = []
    declared = source.get("source") or urlparse(source.get("url", "")).netloc
    for entry in list(entries)[: max(1, per_feed_limit)]:
        title = clean_text(entry.get("title"))
        if not title:
            continue
        if "news.google.com" in source.get("url", ""):
            title = _GNEWS_SUFFIX.sub("", title).strip()
        summary = clean_text(
            entry.get("summary") or entry.get("description") or "", limit=420
        )
        articles.append(
            Article(
                title=title,
                link=_entry_link(entry),
                source=declared,
                feed_name=source.get("name", declared),
                summary=summary,
                published=_parse_date(entry),
                category=source.get("category", "mixed"),
            )
        )
    return articles


def collect(
    sources: list[dict[str, Any]],
    net: dict[str, Any],
    per_feed_limit: int,
    log: Logger,
) -> tuple[list[Article], int, int, list[str]]:
    """Fetch every enabled source concurrently and de-duplicate the results."""
    session = build_session(net)
    workers = max(1, min(int(net.get("concurrency", 8)), 16))
    articles: list[Article] = []
    errors: list[str] = []
    ok = failed = 0

    log("info", f"Fetching {len(sources)} feeds with {workers} workers…")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch_feed, session, src, net, per_feed_limit): src
            for src in sources
        }
        for future in as_completed(futures):
            src = futures[future]
            try:
                items, error = future.result()
            except Exception as exc:  # noqa: BLE001
                items, error = [], f"{type(exc).__name__}: {exc}"
            if error:
                failed += 1
                message = f"{src.get('name', '?')}: {error}"
                errors.append(message)
                log("warn", f"Feed failed — {message}")
            else:
                ok += 1
                articles.extend(items)
                log("debug", f"{src.get('name', '?')}: {len(items)} items")

    session.close()
    deduped = dedupe(articles)
    log(
        "info",
        f"Collected {len(articles)} items from {ok} feeds "
        f"({failed} failed) → {len(deduped)} unique",
    )
    return deduped, ok, failed, errors


def dedupe(articles: list[Article]) -> list[Article]:
    """Drop repeats by URL and by identical headline, keeping the earliest copy."""
    seen_uid: set[str] = set()
    seen_title: dict[str, Article] = {}
    out: list[Article] = []
    for article in articles:
        if article.uid in seen_uid:
            continue
        key = normalize_title(article.title)
        existing = seen_title.get(key)
        if existing is not None:
            # Same headline from another outlet: remember it for corroboration.
            if article.source not in existing.corroborating_sources:
                existing.corroborating_sources.append(article.source)
            continue
        seen_uid.add(article.uid)
        seen_title[key] = article
        out.append(article)
    return out
