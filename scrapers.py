"""
scrapers.py — Real-time news aggregation for crude oil analysis.

Sources:
  • Google News RSS  (no auth required)
  • Twitter/X API v2 (requires TWITTER_BEARER_TOKEN env var)
    Falls back gracefully to Google-only mode if token is absent.
"""

from __future__ import annotations

import os
import time
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Article:
    source: str          # "google_news" | "twitter"
    title: str
    summary: str
    url: str
    published: str       # ISO-8601 string
    author: str = ""


# ── Google News RSS ───────────────────────────────────────────────────────────

GOOGLE_RSS_BASE = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-US&gl=US&ceid=US:en"
)

GOOGLE_QUERIES = [
    "crude oil price",
    "WTI Brent oil",
    "OPEC oil supply",
    "oil Strait Hormuz Iran",
    "oil energy geopolitics",
]


def _parse_google_entry(entry) -> Article:
    summary = getattr(entry, "summary", "") or ""
    # Strip HTML tags from Google News summaries
    if "<" in summary:
        import re
        summary = re.sub(r"<[^>]+>", " ", summary).strip()
    summary = textwrap.shorten(summary, width=300, placeholder="…")

    published = getattr(entry, "published", "") or datetime.now(timezone.utc).isoformat()

    return Article(
        source="google_news",
        title=entry.get("title", "").split(" - ")[0].strip(),
        summary=summary,
        url=entry.get("link", ""),
        published=published,
        author=entry.get("author", ""),
    )


def fetch_google_news(max_per_query: int = 5) -> list[Article]:
    """Pull top headlines from Google News RSS across all oil-related queries."""
    seen_urls: set[str] = set()
    articles: list[Article] = []

    for query in GOOGLE_QUERIES:
        url = GOOGLE_RSS_BASE.format(query=query.replace(" ", "+"))
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_query]:
                link = entry.get("link", "")
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                articles.append(_parse_google_entry(entry))
        except Exception as exc:
            print(f"[scrapers] Google RSS error for '{query}': {exc}")
        time.sleep(0.3)   # be polite

    return articles


# ── Twitter / X API v2 ────────────────────────────────────────────────────────

TWITTER_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"

TWITTER_QUERIES = [
    "(crude oil OR WTI OR Brent) lang:en -is:retweet",
    "(OPEC OR oil price OR #oilmarket) lang:en -is:retweet",
    "(Strait Hormuz OR Iran oil) lang:en -is:retweet",
]

TWITTER_FIELDS = {
    "tweet.fields": "created_at,author_id,text,public_metrics",
    "expansions": "author_id",
    "user.fields": "name,username",
}


def _bearer_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def fetch_twitter(max_per_query: int = 5) -> list[Article]:
    """
    Fetch recent tweets via Twitter API v2.
    Requires TWITTER_BEARER_TOKEN environment variable.
    Returns an empty list (with a warning) if the token is missing or the
    request fails — the tool degrades gracefully to Google-only mode.
    """
    token = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
    if not token:
        return []

    articles: list[Article] = []
    seen_ids: set[str] = set()

    for query in TWITTER_QUERIES:
        params = {
            "query": query,
            "max_results": max_per_query,
            **TWITTER_FIELDS,
        }
        try:
            resp = requests.get(
                TWITTER_SEARCH_URL,
                headers=_bearer_headers(token),
                params=params,
                timeout=10,
            )
            if resp.status_code == 401:
                print("[scrapers] Twitter: invalid bearer token — skipping Twitter.")
                return []
            if resp.status_code == 429:
                print("[scrapers] Twitter: rate-limited — skipping remaining queries.")
                break
            resp.raise_for_status()

            data = resp.json()
            users = {
                u["id"]: u
                for u in data.get("includes", {}).get("users", [])
            }
            for tweet in data.get("data", []):
                tid = tweet["id"]
                if tid in seen_ids:
                    continue
                seen_ids.add(tid)

                author_id = tweet.get("author_id", "")
                user = users.get(author_id, {})
                username = user.get("username", "unknown")
                name = user.get("name", "")

                articles.append(Article(
                    source="twitter",
                    title=f"@{username} ({name})",
                    summary=textwrap.shorten(tweet["text"], width=280, placeholder="…"),
                    url=f"https://x.com/{username}/status/{tid}",
                    published=tweet.get("created_at", ""),
                    author=username,
                ))
        except requests.RequestException as exc:
            print(f"[scrapers] Twitter error for '{query}': {exc}")
        time.sleep(0.5)

    return articles


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_all_news(
    google_max: int = 5,
    twitter_max: int = 5,
) -> dict[str, list[Article]]:
    """
    Aggregate news from all sources.
    Returns a dict with keys 'google_news' and 'twitter'.
    """
    google = fetch_google_news(max_per_query=google_max)
    twitter = fetch_twitter(max_per_query=twitter_max)

    return {
        "google_news": google,
        "twitter": twitter,
    }


def articles_to_text(news: dict[str, list[Article]]) -> str:
    """Flatten all articles into a single text block for the LLM."""
    lines: list[str] = []

    google = news.get("google_news", [])
    twitter = news.get("twitter", [])

    if google:
        lines.append("=== GOOGLE NEWS ===")
        for i, a in enumerate(google, 1):
            lines.append(f"[{i}] {a.title}")
            if a.summary:
                lines.append(f"    {a.summary}")
            lines.append(f"    Published: {a.published}  |  {a.url}")
            lines.append("")

    if twitter:
        lines.append("=== TWITTER / X ===")
        for i, a in enumerate(twitter, 1):
            lines.append(f"[T{i}] {a.title}")
            lines.append(f"    {a.summary}")
            lines.append(f"    Published: {a.published}  |  {a.url}")
            lines.append("")

    if not lines:
        lines.append("No articles fetched. Check network or API credentials.")

    return "\n".join(lines)
