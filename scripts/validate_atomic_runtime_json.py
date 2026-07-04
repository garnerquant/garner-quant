from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.atomic_io import (  # noqa: E402
    assert_no_atomic_artifacts,
    atomic_write_json,
)
from execution.live_market_monitor import (  # noqa: E402
    MonitorJsonStateError,
    load_monitor_snapshot,
)
from runtime.live_runtime import RuntimeJsonStateError, load_status  # noqa: E402


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def scratch_path(token, name):
    return ROOT / f"atomic_json_{token}_{name}.json"


def cleanup(path):
    path.unlink(missing_ok=True)
    for artifact in ROOT.glob(f".{path.name}.atomic-*"):
        artifact.unlink(missing_ok=True)


def simulate_failure(stage_to_fail):
    token = uuid4().hex
    path = scratch_path(token, "runtime_state")
    original = {"status": "original", "count": 1}
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
            atomic_write_json(
                {"status": "updated", "count": 2},
                path,
                failure_hook=failure_hook,
            )
        except Exception:
            pass

        artifacts = list(ROOT.glob(f".{path.name}.atomic-*"))
        return json.loads(path.read_text(encoding="utf-8")) == original and not artifacts
    finally:
        cleanup(path)


def simulate_success():
    token = uuid4().hex
    path = scratch_path(token, "runtime_success")
    expected = {"status": "updated", "nested": {"ok": True}}

    try:
        atomic_write_json(expected, path)
        artifacts = list(ROOT.glob(f".{path.name}.atomic-*"))
        return json.loads(path.read_text(encoding="utf-8")) == expected and not artifacts
    finally:
        cleanup(path)


def corrupt_runtime_load_raises():
    token = uuid4().hex
    path = scratch_path(token, "corrupt_status")
    path.write_text("{not-json", encoding="utf-8")
    try:
        try:
            load_status(path)
        except RuntimeJsonStateError:
            return True
        return False
    finally:
        cleanup(path)


def corrupt_monitor_load_raises():
    token = uuid4().hex
    path = scratch_path(token, "corrupt_monitor")
    path.write_text("{not-json", encoding="utf-8")
    try:
        try:
            load_monitor_snapshot(path)
        except MonitorJsonStateError:
            return True
        return False
    finally:
        cleanup(path)


def startup_artifact_detection_catches_json():
    token = uuid4().hex
    path = ROOT / "data" / f".runtime_state_{token}.json.atomic-test.tmp"
    path.write_text("{}", encoding="utf-8")
    try:
        try:
            assert_no_atomic_artifacts(ROOT)
        except Exception:
            return True
        return False
    finally:
        path.unlink(missing_ok=True)


def runtime_modules_have_no_direct_json_writes():
    files = [
        ROOT / "runtime" / "live_runtime.py",
        ROOT / "execution" / "live_market_monitor.py",
        ROOT / "execution" / "portfolio_manager.py",
    ]
    for path in files:
        source = path.read_text(encoding="utf-8")
        if ".write_text(" in source:
            return False
    return True


def production_runtime_json_parseable():
    files = [
        ROOT / "data" / "live_runtime_status.json",
        ROOT / "data" / "live_runtime_execution_log.json",
        ROOT / "data" / "runtime_operations_log.json",
        ROOT / "data" / "live_monitor_snapshot.json",
        ROOT / "data" / "live_monitor_runtime.json",
        ROOT / "data" / "runtime_decision_trace.json",
    ]
    for path in files:
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))
    return True


def main():
    issues = []

    try:
        assert_no_atomic_artifacts(ROOT)
        no_artifacts = True
    except Exception as exc:
        print(exc)
        no_artifacts = False

    check(no_artifacts, "no unfinished atomic artifacts exist", issues)
    check(production_runtime_json_parseable(), "runtime JSON files are parseable", issues)
    check(
        runtime_modules_have_no_direct_json_writes(),
        "runtime JSON state modules have no direct write_text path",
        issues,
    )
    check(simulate_success(), "atomic JSON success writes parseable final JSON", issues)
    check(
        simulate_failure("after_temp_write"),
        "temp-write failure leaves runtime JSON unchanged",
        issues,
    )
    check(
        simulate_failure("after_replace"),
        "replace failure rolls back runtime JSON",
        issues,
    )
    check(
        startup_artifact_detection_catches_json(),
        "startup atomic artifact detection catches JSON temp files",
        issues,
    )
    check(
        corrupt_runtime_load_raises(),
        "corrupt runtime JSON state raises instead of resetting to empty",
        issues,
    )
    check(
        corrupt_monitor_load_raises(),
        "corrupt monitor JSON state raises instead of resetting to empty",
        issues,
    )

    if issues:
        print("\nAtomic runtime JSON validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nAtomic runtime JSON validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
