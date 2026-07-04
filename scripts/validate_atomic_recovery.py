from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.atomic_io import (  # noqa: E402
    AtomicRecoveryError,
    atomic_artifacts,
    recover_atomic_artifacts,
)


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def paths(label, transaction_id=None):
    transaction_id = transaction_id or uuid4().hex
    final = ROOT / f"atomic_recovery_{label}.json"
    temp = final.with_name(f".{final.name}.atomic-{transaction_id}.tmp")
    backup = final.with_name(f".{final.name}.atomic-{transaction_id}.bak")
    return final, temp, backup


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2), encoding="utf-8")


def cleanup(*items):
    for path in items:
        path = Path(path)
        path.unlink(missing_ok=True)
        for artifact in ROOT.glob(f".{path.name}.atomic-*"):
            artifact.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def crash_after_temp_write():
    final, temp, backup = paths("after_temp")
    cleanup(final)
    write_json(final, {"state": "final"})
    write_json(temp, {"state": "temp"})
    try:
        actions = recover_atomic_artifacts(ROOT)
        return (
            read_json(final) == {"state": "final"}
            and not temp.exists()
            and not backup.exists()
            and actions
        )
    finally:
        cleanup(final, temp, backup)


def crash_after_first_replace():
    final, temp, backup = paths("after_replace")
    cleanup(final)
    write_json(temp, {"state": "new"})
    write_json(backup, {"state": "old"})
    try:
        actions = recover_atomic_artifacts(ROOT)
        return (
            read_json(final) == {"state": "old"}
            and not temp.exists()
            and not backup.exists()
            and actions
        )
    finally:
        cleanup(final, temp, backup)


def crash_during_rollback():
    final, temp, backup = paths("rollback")
    cleanup(final)
    write_json(final, {"state": "old-restored"})
    write_json(backup, {"state": "old"})
    try:
        actions = recover_atomic_artifacts(ROOT)
        return (
            read_json(final) == {"state": "old-restored"}
            and not temp.exists()
            and not backup.exists()
            and actions
        )
    finally:
        cleanup(final, temp, backup)


def multiple_leftover_artifacts():
    first_final, first_temp, first_backup = paths("multi_first")
    second_final, second_temp, second_backup = paths("multi_second")
    cleanup(first_final, second_final)
    write_json(first_final, {"state": "first"})
    write_json(first_temp, {"state": "first-temp"})
    write_json(second_temp, {"state": "second-temp"})
    write_json(second_backup, {"state": "second-backup"})
    try:
        actions = recover_atomic_artifacts(ROOT)
        return (
            read_json(first_final) == {"state": "first"}
            and read_json(second_final) == {"state": "second-backup"}
            and not first_temp.exists()
            and not second_temp.exists()
            and not second_backup.exists()
            and len(actions) >= 2
        )
    finally:
        cleanup(first_final, first_temp, first_backup)
        cleanup(second_final, second_temp, second_backup)


def ambiguous_temp_only_fails_closed():
    final, temp, backup = paths("ambiguous")
    cleanup(final)
    write_json(temp, {"state": "temp-only"})
    try:
        try:
            recover_atomic_artifacts(ROOT)
        except AtomicRecoveryError:
            return temp.exists() and not final.exists() and not backup.exists()
        return False
    finally:
        cleanup(final, temp, backup)


def rerun_recovery_twice():
    final, temp, backup = paths("twice")
    cleanup(final)
    write_json(final, {"state": "final"})
    write_json(temp, {"state": "temp"})
    try:
        recover_atomic_artifacts(ROOT)
        second_actions = recover_atomic_artifacts(ROOT)
        return (
            read_json(final) == {"state": "final"}
            and not temp.exists()
            and not backup.exists()
            and second_actions == []
        )
    finally:
        cleanup(final, temp, backup)


def artifact_inventory_shape():
    final, temp, backup = paths("inventory")
    cleanup(final)
    write_json(temp, {"state": "temp"})
    write_json(backup, {"state": "backup"})
    try:
        artifacts = [
            artifact
            for artifact in atomic_artifacts(ROOT)
            if artifact.final_path == final
        ]
        kinds = sorted(artifact.kind for artifact in artifacts)
        return kinds == ["bak", "tmp"] and all(
            artifact.transaction_id for artifact in artifacts
        )
    finally:
        cleanup(final, temp, backup)


def no_leftover_recovery_artifacts():
    return not [
        artifact
        for artifact in atomic_artifacts(ROOT)
        if artifact.final_path.name.startswith("atomic_recovery_")
    ]


def main():
    issues = []

    check(artifact_inventory_shape(), "atomic artifact inventory parses tmp/bak", issues)
    check(crash_after_temp_write(), "crash after temp write removes temp", issues)
    check(crash_after_first_replace(), "crash after first replace restores backup", issues)
    check(crash_during_rollback(), "crash during rollback removes leftover backup", issues)
    check(multiple_leftover_artifacts(), "multiple leftover artifacts recover", issues)
    check(ambiguous_temp_only_fails_closed(), "ambiguous temp-only state fails closed", issues)
    check(rerun_recovery_twice(), "recovery is idempotent when rerun", issues)
    check(no_leftover_recovery_artifacts(), "recovery simulation leaves no artifacts", issues)

    if issues:
        print("\nAtomic recovery validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nAtomic recovery validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
