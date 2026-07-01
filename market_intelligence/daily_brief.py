from market_intelligence.market_calendar import macro_calendar
from market_intelligence.news_analyzer import analyze_stories
from market_intelligence.news_sources import collect_stories
from market_intelligence.news_store import (
    dedupe_stories,
    load_store,
    save_store,
    utc_timestamp,
)
from market_intelligence.ticker_mapper import intelligence_context


MARKET_INTELLIGENCE_ENABLED = True
MARKET_INTELLIGENCE_MAX_ITEMS = 100


def portfolio_exposure(stories, context):
    holdings = set(context.get("current_holdings", []))
    signals = set(context.get("todays_signals", []))
    exposure = []
    for ticker in context.get("all_tickers", []):
        ticker_stories = [
            story
            for story in stories
            if ticker in story.get("matched_tickers", [])
        ]
        if not ticker_stories:
            continue
        exposure.append(
            {
                "ticker": ticker,
                "stories_count": len(ticker_stories),
                "in_current_holdings": ticker in holdings,
                "in_todays_signals": ticker in signals,
                "highest_importance": highest_importance(ticker_stories),
            }
        )
    return sorted(
        exposure,
        key=lambda row: (importance_rank(row["highest_importance"]), row["stories_count"]),
        reverse=True,
    )


def importance_rank(value):
    return {"high": 3, "medium": 2, "low": 1}.get(str(value).lower(), 0)


def highest_importance(stories):
    if any(story.get("importance") == "high" for story in stories):
        return "high"
    if any(story.get("importance") == "medium" for story in stories):
        return "medium"
    if stories:
        return "low"
    return "unknown"


def top_stories(stories, limit=5):
    return sorted(
        stories,
        key=lambda story: (
            importance_rank(story.get("importance")),
            story.get("published_at") or "",
        ),
        reverse=True,
    )[:limit]


def market_summary(stories, context):
    if not stories:
        return "No relevant market headlines have been collected yet."

    holdings_hits = sum(
        1
        for story in stories
        if set(story.get("matched_tickers", [])).intersection(
            context.get("current_holdings", [])
        )
    )
    high_count = sum(1 for story in stories if story.get("importance") == "high")
    return (
        f"Collected {len(stories)} market headlines. "
        f"{holdings_hits} mention current holdings. "
        f"{high_count} are marked high importance by placeholder rules."
    )


def run_market_intelligence(max_items=MARKET_INTELLIGENCE_MAX_ITEMS):
    existing = load_store()
    context = intelligence_context()

    if not MARKET_INTELLIGENCE_ENABLED:
        data = {
            **existing,
            "generated_at": utc_timestamp(),
            "enabled": False,
            "context": context,
        }
        return save_store(data)

    collected = collect_stories(context)
    analyzed = analyze_stories(collected["stories"], context)
    stories = dedupe_stories(
        analyzed + existing.get("stories", []),
        max_items=max_items,
    )
    calendar = macro_calendar()
    data = {
        "generated_at": utc_timestamp(),
        "version": "market_intelligence_v2",
        "enabled": True,
        "context": context,
        "sources": collected["sources"],
        "stories": stories,
        "portfolio_exposure": portfolio_exposure(stories, context),
        "top_stories": top_stories(stories),
        "macro_calendar": calendar.get("events", []),
        "market_summary": market_summary(stories, context),
        "errors": collected["errors"],
        "max_items": max_items,
        "ai": {
            "enabled": False,
            "summary": None,
            "sentiment": None,
            "importance": None,
            "confidence": None,
            "affected_assets": [],
        },
    }
    return save_store(data)


if __name__ == "__main__":
    import json

    print(json.dumps(run_market_intelligence(), indent=2))
