from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from market_intelligence.news_store import story_hash
from market_intelligence.ticker_mapper import query_for_ticker


REQUEST_TIMEOUT_SECONDS = 8


def utc_timestamp(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(unescape(value).split())


def parse_rss_time(value):
    if not value:
        return utc_timestamp()
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return utc_timestamp()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return utc_timestamp(parsed)


@dataclass
class RSSSource:
    name: str
    url: str
    category_hint: str = "Market"
    query_template: bool = False

    def urls_for_context(self, context):
        if not self.query_template:
            return [(self.url, None)]

        urls = []
        for ticker in context.get("all_tickers", [])[:12]:
            query = query_for_ticker(ticker)
            urls.append((self.url.format(query=quote_plus(query)), ticker))
        return urls

    def fetch(self, context):
        stories = []
        errors = []
        for url, ticker in self.urls_for_context(context):
            try:
                stories.extend(self._fetch_url(url, ticker))
            except Exception as exc:
                errors.append(
                    {
                        "source": self.name,
                        "url": url,
                        "ticker": ticker,
                        "error": str(exc),
                        "timestamp": utc_timestamp(),
                    }
                )
        return stories, errors

    def _fetch_url(self, url, ticker=None):
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "GarnerQuantMarketIntelligence/2.0 "
                    "(read-only RSS monitoring)"
                )
            },
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            feed_bytes = response.read()

        root = ET.fromstring(feed_bytes)
        stories = []
        for item in root.findall(".//item"):
            headline = clean_text(item.findtext("title"))
            story_url = (item.findtext("link") or "").strip()
            summary = clean_text(item.findtext("description"))
            if not headline and not story_url:
                continue
            story = {
                "headline": headline,
                "source": self.name,
                "url": story_url,
                "published_at": parse_rss_time(item.findtext("pubDate")),
                "summary": summary,
                "matched_tickers": [ticker] if ticker else [],
                "category": self.category_hint,
                "importance": None,
                "sentiment": None,
                "hash": None,
            }
            story["hash"] = story_hash(story)
            stories.append(story)
        return stories


SOURCES = [
    RSSSource(
        "Watcher.Guru",
        "https://watcher.guru/news/feed",
        category_hint="Crypto",
    ),
    RSSSource(
        "Google News RSS",
        "https://news.google.com/rss/search?q={query}%20stock%20OR%20market&hl=en-GB&gl=GB&ceid=GB:en",
        query_template=True,
    ),
    RSSSource(
        "Reuters RSS",
        "https://feeds.reuters.com/reuters/businessNews",
        category_hint="Market",
    ),
    RSSSource(
        "CNBC RSS",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        category_hint="Market",
    ),
    RSSSource(
        "Yahoo Finance RSS",
        "https://finance.yahoo.com/news/rssindex",
        category_hint="Market",
    ),
]


def collect_stories(context, sources=None):
    stories = []
    errors = []
    used_sources = sources or SOURCES
    for source in used_sources:
        source_stories, source_errors = source.fetch(context)
        stories.extend(source_stories)
        errors.extend(source_errors)
    return {
        "stories": stories,
        "errors": errors,
        "sources": [source.name for source in used_sources],
    }

