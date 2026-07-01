import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


STORE_PATH = Path("data/market_intelligence.json")


def utc_timestamp(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return value


def story_hash(story):
    url = normalize_text(story.get("url"))
    headline = normalize_text(story.get("headline"))
    return hashlib.sha256(f"{url}|{headline}".encode("utf-8")).hexdigest()


def empty_store():
    return {
        "generated_at": None,
        "version": "market_intelligence_v2",
        "stories_count": 0,
        "stories": [],
        "portfolio_exposure": [],
        "top_stories": [],
        "macro_calendar": [],
        "market_summary": "No market intelligence has been collected yet.",
        "sources": [],
        "errors": [],
    }


def load_store(path=STORE_PATH):
    path = Path(path)
    if not path.exists():
        return empty_store()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    base = empty_store()
    base.update(data if isinstance(data, dict) else {})
    base["stories"] = base.get("stories") or []
    base["stories_count"] = len(base["stories"])
    return base


def dedupe_stories(stories, max_items=100):
    deduped = []
    seen = set()
    for story in sorted(
        stories,
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    ):
        story = dict(story)
        story["hash"] = story.get("hash") or story_hash(story)
        url_key = normalize_text(story.get("url"))
        headline_key = normalize_text(story.get("headline"))
        keys = {story["hash"], f"url:{url_key}", f"headline:{headline_key}"}
        if seen.intersection(keys):
            continue
        seen.update(keys)
        deduped.append(story)
        if len(deduped) >= max_items:
            break
    return deduped


def save_store(data, path=STORE_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["stories"] = dedupe_stories(data.get("stories", []), data.get("max_items", 100))
    data["stories_count"] = len(data["stories"])
    data["generated_at"] = data.get("generated_at") or utc_timestamp()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data

