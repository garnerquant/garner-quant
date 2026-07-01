from datetime import datetime, timezone


STATIC_MACRO_EVENTS = [
    {
        "event": "US Federal Reserve policy and rate commentary",
        "category": "Central Banks",
        "importance": "high",
        "region": "US",
    },
    {
        "event": "Bank of England policy and inflation commentary",
        "category": "Central Banks",
        "importance": "high",
        "region": "UK",
    },
    {
        "event": "US CPI / inflation releases",
        "category": "Macro",
        "importance": "high",
        "region": "US",
    },
    {
        "event": "US non-farm payrolls",
        "category": "Macro",
        "importance": "medium",
        "region": "US",
    },
    {
        "event": "Major technology earnings season",
        "category": "Earnings",
        "importance": "medium",
        "region": "US",
    },
]


def macro_calendar():
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": STATIC_MACRO_EVENTS,
        "note": (
            "Static v2 placeholder. Future versions can replace this with an "
            "economic calendar provider."
        ),
    }

