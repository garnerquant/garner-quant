from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.atomic_io import assert_no_atomic_artifacts  # noqa: E402
from market_intelligence.news_store import (  # noqa: E402
    MarketIntelligenceStoreError,
    load_store,
    save_store,
)
from news.news_monitor import (  # noqa: E402
    NewsEventsStateError,
    load_news_events,
    save_news_events,
)
from notifications.alert_notifier import (  # noqa: E402
    NotificationStateError,
    load_notification_state,
    save_notification_state,
)


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def scratch_path(token, label):
    return ROOT / f"atomic_notification_intelligence_{token}_{label}.json"


def cleanup(path):
    path.unlink(missing_ok=True)
    for artifact in ROOT.glob(f".{path.name}.atomic-*"):
        artifact.unlink(missing_ok=True)


def simulate_save_failure(save_func, payload, label, stage_to_fail):
    token = uuid4().hex
    path = scratch_path(token, label)
    original = {"state": "original", "label": label}
    path.write_text(json.dumps(original, indent=2), encoding="utf-8")
    replaced = 0

    def failure_hook(stage, _target):
        nonlocal replaced
        if stage_to_fail == "after_temp_write" and stage == "after_temp_write":
            raise RuntimeError("simulated temp barrier failure")
        if stage_to_fail == "after_replace" and stage == "after_replace":
            replaced += 1
            if replaced == 1:
                raise RuntimeError("simulated replace failure")

    try:
        try:
            save_func(payload, path=path, failure_hook=failure_hook)
        except Exception:
            pass
        artifacts = list(ROOT.glob(f".{path.name}.atomic-*"))
        return json.loads(path.read_text(encoding="utf-8")) == original and not artifacts
    finally:
        cleanup(path)


def corrupt_load_raises(load_func, expected_error, label):
    token = uuid4().hex
    path = scratch_path(token, label)
    path.write_text("{not-json", encoding="utf-8")
    try:
        try:
            load_func(path)
        except expected_error:
            return True
        return False
    finally:
        cleanup(path)


def production_json_parseable():
    files = [
        ROOT / "data" / "notification_state.json",
        ROOT / "data" / "market_intelligence.json",
        ROOT / "data" / "news_events.json",
    ]
    for path in files:
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))
    return True


def scoped_modules_have_no_direct_json_writes():
    files = [
        ROOT / "notifications" / "alert_notifier.py",
        ROOT / "market_intelligence" / "news_store.py",
        ROOT / "news" / "news_monitor.py",
    ]
    for path in files:
        source = path.read_text(encoding="utf-8")
        if ".write_text(" in source:
            return False
    return True


def startup_artifact_detection_catches_scoped_json():
    token = uuid4().hex
    path = ROOT / "data" / f".notification_state_{token}.json.atomic-test.tmp"
    path.write_text("{}", encoding="utf-8")
    try:
        try:
            assert_no_atomic_artifacts(ROOT)
        except Exception:
            return True
        return False
    finally:
        path.unlink(missing_ok=True)


def main():
    issues = []

    try:
        assert_no_atomic_artifacts(ROOT)
        no_artifacts = True
    except Exception as exc:
        print(exc)
        no_artifacts = False

    check(no_artifacts, "no unfinished atomic artifacts exist", issues)
    check(
        production_json_parseable(),
        "notification/intelligence JSON files are parseable",
        issues,
    )
    check(
        scoped_modules_have_no_direct_json_writes(),
        "notification/intelligence modules have no direct write_text path",
        issues,
    )
    check(
        simulate_save_failure(
            save_notification_state,
            {"sent_alerts": {}, "sent_trades": {}},
            "notification",
            "after_temp_write",
        ),
        "notification temp-write failure leaves state unchanged",
        issues,
    )
    check(
        simulate_save_failure(
            save_notification_state,
            {"sent_alerts": {}, "sent_trades": {}},
            "notification",
            "after_replace",
        ),
        "notification replace failure rolls back state",
        issues,
    )
    check(
        simulate_save_failure(
            save_store,
            {"stories": [{"headline": "Test", "url": "https://example.test"}]},
            "market_intelligence",
            "after_replace",
        ),
        "market intelligence replace failure rolls back store",
        issues,
    )
    check(
        simulate_save_failure(
            save_news_events,
            {"items": [{"title": "Test", "url": "https://example.test"}]},
            "news_events",
            "after_replace",
        ),
        "news events replace failure rolls back cache",
        issues,
    )
    check(
        startup_artifact_detection_catches_scoped_json(),
        "startup artifact detection catches notification JSON temp files",
        issues,
    )
    check(
        corrupt_load_raises(
            load_notification_state,
            NotificationStateError,
            "corrupt_notification",
        ),
        "corrupt notification state raises explicitly",
        issues,
    )
    check(
        corrupt_load_raises(
            load_store,
            MarketIntelligenceStoreError,
            "corrupt_market_intelligence",
        ),
        "corrupt market intelligence store raises explicitly",
        issues,
    )
    check(
        corrupt_load_raises(
            load_news_events,
            NewsEventsStateError,
            "corrupt_news_events",
        ),
        "corrupt news events cache raises explicitly",
        issues,
    )

    if issues:
        print("\nAtomic notification/intelligence validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nAtomic notification/intelligence validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
