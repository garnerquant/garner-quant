from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import json
from pathlib import Path
import re
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import pandas as pd

from news.news_config import (
    NEWS_FEEDS,
    NEWS_MAX_ITEMS,
    NEWS_MONITOR_ENABLED,
    NEWS_QUERY_ALIASES,
    NEWS_REQUEST_TIMEOUT_SECONDS,
)


NEWS_EVENTS_FILE = Path("data/news_events.json")
SIGNAL_REPORT_FILE = Path("signal_report_v2.csv")


def utc_timestamp(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def load_news_events(path=NEWS_EVENTS_FILE):
    path = Path(path)
    if not path.exists():
        return {
            "generated_at": None,
            "monitor_enabled": NEWS_MONITOR_ENABLED,
            "items_count": 0,
            "items": [],
            "errors": [],
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    data.setdefault("generated_at", None)
    data.setdefault("monitor_enabled", NEWS_MONITOR_ENABLED)
    data.setdefault("items_count", len(data.get("items", [])))
    data.setdefault("items", [])
    data.setdefault("errors", [])
    return data


def save_news_events(data, path=NEWS_EVENTS_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def configured_tickers(extra_tickers=None):
    tickers = []
    if extra_tickers:
        tickers.extend(str(ticker).strip() for ticker in extra_tickers)

    try:
        from execution.live_market_monitor import load_current_holding_tickers

        tickers.extend(load_current_holding_tickers())
    except Exception:
        pass

    if SIGNAL_REPORT_FILE.exists():
        try:
            signals = pd.read_csv(SIGNAL_REPORT_FILE)
            if "ticker" in signals.columns:
                tickers.extend(signals["ticker"].dropna().astype(str).tolist())
        except Exception:
            pass

    unique = []
    seen = set()
    for ticker in tickers:
        ticker = str(ticker or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        unique.append(ticker)

    return unique


def query_for_ticker(ticker):
    ticker = str(ticker or "").strip().upper()
    return NEWS_QUERY_ALIASES.get(ticker, ticker)


def strip_html(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(unescape(value).split())


def parse_rss_timestamp(value):
    if not value:
        return utc_timestamp()

    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return utc_timestamp()

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return utc_timestamp(parsed)


def fetch_feed(url, timeout=NEWS_REQUEST_TIMEOUT_SECONDS):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "GarnerQuantNewsMonitor/1.0 "
                "(read-only RSS monitoring; no trading decisions)"
            )
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def parse_feed_items(feed_bytes, source, ticker, query):
    root = ET.fromstring(feed_bytes)
    items = []
    for item in root.findall(".//item"):
        title = strip_html(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        summary = strip_html(item.findtext("description"))
        published = parse_rss_timestamp(item.findtext("pubDate"))
        if not title and not url:
            continue
        items.append(
            {
                "timestamp": published,
                "source": source,
                "title": title,
                "url": url,
                "ticker": ticker,
                "query": query,
                "summary": summary,
                "sentiment": "unknown",
                "importance": "unknown",
            }
        )
    return items


def dedupe_items(items, max_items=NEWS_MAX_ITEMS):
    deduped = []
    seen = set()
    for item in sorted(
        items,
        key=lambda row: row.get("timestamp") or "",
        reverse=True,
    ):
        key = (
            (item.get("url") or "").strip().lower(),
            (item.get("title") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def run_news_monitor(tickers=None, max_items=NEWS_MAX_ITEMS, path=NEWS_EVENTS_FILE):
    existing = load_news_events(path)
    errors = []
    fetched_items = []
    monitored_tickers = configured_tickers(tickers)

    if not NEWS_MONITOR_ENABLED:
        data = {
            **existing,
            "generated_at": utc_timestamp(),
            "monitor_enabled": False,
            "monitored_tickers": monitored_tickers,
            "items_count": len(existing.get("items", [])),
            "errors": [],
        }
        return save_news_events(data, path)

    for ticker in monitored_tickers:
        query = query_for_ticker(ticker)
        for feed in NEWS_FEEDS:
            url = feed["url"].format(query=quote_plus(query))
            try:
                feed_bytes = fetch_feed(url)
                fetched_items.extend(
                    parse_feed_items(
                        feed_bytes,
                        feed.get("source", "RSS"),
                        ticker,
                        query,
                    )
                )
            except Exception as exc:
                errors.append(
                    {
                        "timestamp": utc_timestamp(),
                        "ticker": ticker,
                        "query": query,
                        "source": feed.get("source", "RSS"),
                        "error": str(exc),
                    }
                )

    items = dedupe_items(
        fetched_items + existing.get("items", []),
        max_items=max_items,
    )
    data = {
        "generated_at": utc_timestamp(),
        "monitor_enabled": True,
        "monitored_tickers": monitored_tickers,
        "sources": [feed.get("source", "RSS") for feed in NEWS_FEEDS],
        "items_count": len(items),
        "items": items,
        "errors": errors,
    }
    return save_news_events(data, path)


if __name__ == "__main__":
    result = run_news_monitor()
    print(json.dumps(result, indent=2))
