"""Filtering, topic classification, region detection and importance scoring.

Everything here is deterministic and runs before the AI step, so the article
list is still useful (and still ranked) when no provider is configured.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from .models import (
    CATEGORY_FINANCIAL,
    CATEGORY_MILITARY,
    CATEGORY_OTHER,
    IMPORTANCE_HIGH,
    IMPORTANCE_LOW,
    IMPORTANCE_MEDIUM,
    Article,
    title_tokens,
)

Logger = Callable[[str, str], None]

MILITARY_TERMS = {
    "military", "army", "navy", "air force", "troops", "soldier", "soldiers",
    "missile", "missiles", "drone", "drones", "airstrike", "air strike",
    "strike", "strikes", "offensive", "ceasefire", "armistice", "war",
    "warfare", "combat", "battalion", "brigade", "artillery", "shelling",
    "insurgent", "insurgency", "militant", "militants", "nato", "pentagon",
    "defence", "defense", "warship", "submarine", "fighter jet", "warplane",
    "rebels", "paramilitary", "mobilisation", "mobilization", "conscription",
    "arms deal", "weapons", "munitions", "nuclear", "ballistic", "hypersonic",
    "peacekeeping", "occupation", "invasion", "incursion", "frontline",
    "front line", "casualties", "hostage", "hostages", "coup", "junta",
    "border clash", "airspace", "no-fly", "arms embargo", "security council",
    "reservist", "reservists", "garrison", "barracks", "frigate", "regiment",
    "marines", "airbase", "air base", "shipyard", "dockyard", "naval",
    "cyber command", "veterans", "aircraft carrier", "helicopter fleet",
}

FINANCIAL_TERMS = {
    "market", "markets", "stocks", "stock", "shares", "equities", "bond",
    "bonds", "yield", "yields", "treasury", "inflation", "deflation", "cpi",
    "gdp", "recession", "economy", "economic", "central bank", "federal reserve",
    "fed", "ecb", "boe", "interest rate", "rate cut", "rate hike", "monetary",
    "fiscal", "budget", "deficit", "debt", "default", "currency", "dollar",
    "euro", "yen", "yuan", "forex", "commodity", "commodities", "oil price",
    "crude", "opec", "gold", "earnings", "revenue", "profit", "ipo", "merger",
    "acquisition", "bankruptcy", "layoffs", "unemployment", "jobs report",
    "payrolls", "tariff", "tariffs", "trade deal", "sanctions", "nasdaq",
    "s&p", "dow", "ftse", "nikkei", "crypto", "bitcoin", "valuation",
    "hedge fund", "private equity", "banking", "lender", "credit",
}

# Weighted signals of a genuinely consequential story.
CRITICAL_TERMS = {
    "invasion", "invades", "declares war", "nuclear", "ceasefire", "collapse",
    "default", "emergency", "assassinat", "coup", "state of emergency",
    "mass casualt", "crash", "bailout", "martial law", "evacuat",
}
HIGH_TERMS = {
    "airstrike", "air strike", "offensive", "sanctions", "sanction",
    "rate cut", "rate hike", "recession", "escalat", "missile", "troops",
    "strike", "attack", "drone", "shelling", "explosion", "blast", "raid",
    "clash", "seize", "seizes", "killed", "casualt", "wounded", "captured",
    "tariff", "resign", "shutdown", "record high", "record low", "plunge",
    "surge", "warning", "breach", "treaty", "summit", "election",
    "bankruptcy", "layoffs", "inflation", "downgrade", "blockade",
}
MEDIUM_TERMS = {
    "talks", "meeting", "report", "forecast", "outlook", "deal", "agreement",
    "probe", "investigation", "lawsuit", "earnings", "results", "plan",
    "proposal", "shares", "growth", "decline", "review",
}

TIER1_SOURCES = {
    "Reuters", "Associated Press", "BBC", "New York Times", "Financial Times",
    "Bloomberg", "Federal Reserve", "US Dept. of Defense",
}
TIER2_SOURCES = {"CNBC", "CNN", "The Guardian", "Al Jazeera", "MarketWatch"}

REGION_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Middle East", (
        "israel", "gaza", "palestin", "hamas", "hezbollah", "lebanon", "syria",
        "iran", "tehran", "iraq", "baghdad", "yemen", "houthi", "saudi",
        "riyadh", "qatar", "doha", "uae", "dubai", "abu dhabi", "jordan",
        "kuwait", "bahrain", "oman", "west bank", "jerusalem", "red sea",
        "strait of hormuz", "middle east",
    )),
    ("Eastern Europe", (
        "ukraine", "kyiv", "kiev", "russia", "moscow", "kremlin", "putin",
        "belarus", "minsk", "crimea", "donetsk", "luhansk", "kharkiv",
        "odesa", "odessa", "zelensky", "poland", "warsaw", "baltic",
        "estonia", "latvia", "lithuania", "moldova", "romania", "bucharest",
    )),
    ("Europe", (
        "europe", "european union", " eu ", "brussels", "nato", "germany",
        "berlin", "france", "paris", "britain", "uk ", "united kingdom",
        "london", "italy", "rome", "spain", "madrid", "netherlands",
        "amsterdam", "sweden", "norway", "denmark", "finland", "switzerland",
        "greece", "portugal", "ireland", "austria", "belgium", "ecb",
        "eurozone", "ftse", "dax",
    )),
    ("East Asia", (
        "china", "beijing", "shanghai", "taiwan", "taipei", "hong kong",
        "japan", "tokyo", "korea", "seoul", "pyongyang", "north korea",
        "south china sea", "east china sea", "nikkei", "hang seng", "yuan",
        "xi jinping",
    )),
    ("South Asia", (
        "india", "delhi", "mumbai", "pakistan", "islamabad", "karachi",
        "kashmir", "afghanistan", "kabul", "taliban", "bangladesh", "dhaka",
        "sri lanka", "colombo", "nepal", "myanmar", "burma",
    )),
    ("Southeast Asia & Pacific", (
        "indonesia", "jakarta", "philippines", "manila", "vietnam", "hanoi",
        "thailand", "bangkok", "malaysia", "singapore", "australia",
        "canberra", "sydney", "new zealand", "pacific", "aukus",
    )),
    ("North America", (
        "united states", "u.s.", "us ", "usa", "american", "washington",
        "white house", "pentagon", "congress", "senate", "capitol hill",
        "federal reserve", " fed ", "fomc", "wall street",
        "new york", "california", "texas", "canada", "ottawa", "toronto",
        "mexico", "mexico city", "nasdaq", "s&p 500", "dow jones",
    )),
    ("Latin America", (
        "brazil", "brasilia", "sao paulo", "argentina", "buenos aires",
        "venezuela", "caracas", "colombia", "bogota", "chile", "santiago",
        "peru", "lima", "cuba", "havana", "haiti", "ecuador", "bolivia",
        "latin america",
    )),
    ("Africa", (
        "africa", "nigeria", "abuja", "lagos", "egypt", "cairo", "ethiopia",
        "addis", "kenya", "nairobi", "south africa", "johannesburg",
        "pretoria", "sudan", "khartoum", "libya", "tripoli", "algeria",
        "morocco", "tunisia", "somalia", "mogadishu", "mali", "sahel",
        "congo", "rwanda", "zimbabwe", "ghana",
    )),
]


def _haystack(article: Article) -> str:
    return f" {article.title} {article.summary} ".lower()


def _count_terms(text: str, terms: Iterable[str]) -> int:
    return sum(1 for term in terms if term in text)


def classify(article: Article) -> str:
    """Assign military / financial / other, using the feed hint as a tiebreak."""
    text = _haystack(article)
    mil = _count_terms(text, MILITARY_TERMS)
    fin = _count_terms(text, FINANCIAL_TERMS)
    hint = (article.category or "mixed").lower()

    if hint == CATEGORY_MILITARY:
        mil += 2
    elif hint == CATEGORY_FINANCIAL:
        fin += 2

    if mil == 0 and fin == 0:
        return CATEGORY_OTHER
    if mil >= fin:
        return CATEGORY_MILITARY
    return CATEGORY_FINANCIAL


def detect_region(article: Article) -> str:
    """Pick the region with the strongest keyword presence; 'Global' if none."""
    text = _haystack(article)
    best_region, best_hits = "Global", 0
    for region, keywords in REGION_KEYWORDS:
        hits = _count_terms(text, keywords)
        # Headline mentions weigh double — the headline names the main location.
        title = f" {article.title.lower()} "
        hits += _count_terms(title, keywords)
        if hits > best_hits:
            best_region, best_hits = region, hits
    return best_region


def cluster(articles: list[Article], threshold: float = 0.5) -> None:
    """Group headlines describing the same story so corroboration can score."""
    tokens = [title_tokens(a.title) for a in articles]
    parent = list(range(len(articles)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(len(articles)):
        if len(tokens[i]) < 3:
            continue
        for j in range(i + 1, len(articles)):
            if len(tokens[j]) < 3:
                continue
            overlap = tokens[i] & tokens[j]
            if not overlap:
                continue
            jaccard = len(overlap) / len(tokens[i] | tokens[j])
            if jaccard >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for idx in range(len(articles)):
        groups.setdefault(find(idx), []).append(idx)

    for cluster_id, (_, members) in enumerate(groups.items()):
        sources = {articles[m].source for m in members}
        for m in members:
            article = articles[m]
            article.cluster_id = cluster_id
            extra = sorted(sources - {article.source})
            for src in extra:
                if src not in article.corroborating_sources:
                    article.corroborating_sources.append(src)


def score_article(article: Article) -> tuple[int, list[str]]:
    """Return a 0-100ish importance score plus human-readable reasons."""
    text = _haystack(article)
    score = 0
    reasons: list[str] = []

    critical = _count_terms(text, CRITICAL_TERMS)
    high = _count_terms(text, HIGH_TERMS)
    medium = _count_terms(text, MEDIUM_TERMS)
    if critical:
        score += min(30, 18 + 6 * critical)
        reasons.append("critical-impact language")
    if high:
        score += min(20, 8 * high)
        reasons.append("high-impact language")
    if medium:
        score += min(8, 3 * medium)

    if article.source in TIER1_SOURCES:
        score += 8
        reasons.append("wire/primary source")
    elif article.source in TIER2_SOURCES:
        score += 4

    age = article.age_hours
    if age <= 2:
        score += 8
        reasons.append("breaking (<2h)")
    elif age <= 6:
        score += 5
    elif age <= 12:
        score += 2

    corroboration = len(set(article.corroborating_sources))
    if corroboration >= 2:
        score += 15
        reasons.append(f"reported by {corroboration + 1} outlets")
    elif corroboration == 1:
        score += 8
        reasons.append("corroborated by a second outlet")

    if article.category in (CATEGORY_MILITARY, CATEGORY_FINANCIAL):
        score += 5

    # Headlines that name a policy actor tend to matter more.
    if re.search(
        r"\b(fed|ecb|nato|un|imf|opec|white house|pentagon|kremlin|treasury)\b",
        text,
    ):
        score += 6
        reasons.append("institutional actor")

    return min(score, 100), reasons


def grade(score: int) -> str:
    if score >= 48:
        return IMPORTANCE_HIGH
    if score >= 26:
        return IMPORTANCE_MEDIUM
    return IMPORTANCE_LOW


def collapse_clusters(articles: list[Article]) -> list[Article]:
    """Keep the best-scoring copy of each story, folding the rest into it.

    Twenty-five feeds carry the same wire story with slightly different
    headlines; without this the list reads as a wall of near-duplicates.
    """
    best: dict[int, Article] = {}
    order: list[int] = []
    for article in articles:
        key = article.cluster_id if article.cluster_id >= 0 else -id(article)
        current = best.get(key)
        if current is None:
            best[key] = article
            order.append(key)
            continue
        winner, loser = (
            (article, current) if article.score > current.score else (current, article)
        )
        if loser.source and loser.source not in winner.corroborating_sources:
            winner.corroborating_sources.append(loser.source)
        best[key] = winner
    return [best[key] for key in order]


def analyze(
    articles: list[Article], collection: dict[str, Any], log: Logger
) -> list[Article]:
    """Filter stale/irrelevant items then classify, locate and rank the rest."""
    max_age = float(collection.get("max_age_hours", 24))
    min_title = int(collection.get("min_title_length", 15))
    keep_other = bool(collection.get("keep_other_category", False))
    max_articles = int(collection.get("max_articles", 120))

    fresh: list[Article] = []
    dropped_old = dropped_short = 0
    for article in articles:
        if len(article.title) < min_title:
            dropped_short += 1
            continue
        if article.published is None:
            # Undated items are kept but treated as older than anything dated.
            fresh.append(article)
            continue
        if article.age_hours > max_age:
            dropped_old += 1
            continue
        fresh.append(article)

    log(
        "info",
        f"Age filter (>{max_age:g}h): dropped {dropped_old} stale, "
        f"{dropped_short} malformed; {len(fresh)} remain",
    )

    cluster(fresh)

    kept: list[Article] = []
    dropped_offtopic = 0
    for article in fresh:
        article.category = classify(article)
        if article.category == CATEGORY_OTHER and not keep_other:
            dropped_offtopic += 1
            continue
        article.region = detect_region(article)
        article.score, article.reasons = score_article(article)
        article.importance = grade(article.score)
        kept.append(article)

    if dropped_offtopic:
        log("info", f"Dropped {dropped_offtopic} items outside military/financial scope")

    if collection.get("collapse_duplicates", True):
        before = len(kept)
        kept = collapse_clusters(kept)
        if before != len(kept):
            log("info", f"Merged {before - len(kept)} duplicate versions of the same stories")
            # Corroboration changed, so the affected scores need refreshing.
            for article in kept:
                article.score, article.reasons = score_article(article)
                article.importance = grade(article.score)

    kept.sort(
        key=lambda a: (
            -a.score,
            a.age_hours if a.published else float("inf"),
            a.title,
        )
    )
    if len(kept) > max_articles:
        log("info", f"Trimming {len(kept)} → top {max_articles} by importance")
        kept = kept[:max_articles]

    counts = {
        "high": sum(1 for a in kept if a.importance == IMPORTANCE_HIGH),
        "medium": sum(1 for a in kept if a.importance == IMPORTANCE_MEDIUM),
        "low": sum(1 for a in kept if a.importance == IMPORTANCE_LOW),
    }
    log(
        "info",
        f"Ranked {len(kept)} stories — {counts['high']} high, "
        f"{counts['medium']} medium, {counts['low']} low",
    )
    return kept
