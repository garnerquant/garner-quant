from market_intelligence.ticker_mapper import match_story_to_tickers


CATEGORY_KEYWORDS = [
    ("Central Banks", ["fed", "federal reserve", "bank of england", "rate decision", "interest rate"]),
    ("Earnings", ["earnings", "revenue", "profit", "guidance", "quarter"]),
    ("Crypto", ["bitcoin", "ethereum", "crypto", "btc", "eth"]),
    ("Commodities", ["gold", "oil", "commodity", "commodities"]),
    ("Politics", ["election", "government", "tariff", "sanction", "politics"]),
    ("Macro", ["inflation", "cpi", "jobs", "payroll", "gdp", "recession"]),
    ("Market", ["stocks", "shares", "market", "nasdaq", "s&p 500", "ftse"]),
]

HIGH_IMPORTANCE_WORDS = [
    "crash",
    "plunge",
    "surge",
    "war",
    "rate decision",
    "sec",
    "lawsuit",
    "bankruptcy",
    "acquisition",
]


def categorize_story(story):
    text = f"{story.get('headline', '')} {story.get('summary', '')}".lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return "Company" if story.get("matched_tickers") else "Market"


def importance_placeholder(story):
    text = f"{story.get('headline', '')} {story.get('summary', '')}".lower()
    if any(word in text for word in HIGH_IMPORTANCE_WORDS):
        return "high"
    if story.get("matched_tickers"):
        return "medium"
    return "low"


def analyze_story(story, context):
    story = dict(story)
    story["matched_tickers"] = match_story_to_tickers(
        story,
        context.get("all_tickers", []),
    )
    story["category"] = story.get("category") or categorize_story(story)
    story["importance"] = story.get("importance") or importance_placeholder(story)
    story["sentiment"] = story.get("sentiment") or "unknown"
    story["confidence"] = story.get("confidence") or "unknown"
    story["affected_assets"] = story.get("affected_assets") or story["matched_tickers"]
    story["ai_summary"] = story.get("ai_summary") or None
    return story


def analyze_stories(stories, context):
    return [analyze_story(story, context) for story in stories]

