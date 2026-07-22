from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.atomic_io import (  # noqa: E402
    atomic_write_csv_frames,
    atomic_write_json,
    recover_atomic_artifacts,
)
from runtime.locks import (  # noqa: E402
    RuntimeWriteLockError,
    acquire_runtime_write_lock,
    read_lock,
)


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def scratch_paths(label):
    token = uuid4().hex
    base = ROOT / f"runtime_lock_{label}_{token}.json"
    lock = ROOT / f"runtime_lock_{label}_{token}.lock"
    return base, lock


def cleanup(*paths):
    for path in paths:
        path = Path(path)
        path.unlink(missing_ok=True)
        for artifact in ROOT.glob(f".{path.name}.atomic-*"):
            artifact.unlink(missing_ok=True)


def write_status(path, value):
    Path(path).write_text(value, encoding="utf-8")


def wait_for_status(path, timeout_seconds=5):
    deadline = time.monotonic() + timeout_seconds
    path = Path(path)
    while time.monotonic() < deadline:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.05)
    return None


def locked_writer_child(lock_path, final_path, status_path, release_path):
    try:
        with acquire_runtime_write_lock(path=lock_path, context="lock_child"):
            write_status(status_path, "locked")
            if wait_for_status(release_path, timeout_seconds=10) != "release":
                raise TimeoutError("holder release handshake timed out")
            atomic_write_json(
                {"writer": "first"},
                final_path,
                lock_path=lock_path,
            )
    except Exception as exc:
        write_status(status_path, f"error:{type(exc).__name__}:{exc}")


def blocked_writer_child(lock_path, final_path, status_path):
    try:
        atomic_write_json(
            {"writer": "second"},
            final_path,
            lock_path=lock_path,
        )
        write_status(status_path, "wrote")
    except RuntimeWriteLockError:
        write_status(status_path, "blocked")
    except Exception as exc:
        write_status(status_path, f"error:{type(exc).__name__}:{exc}")


def waiting_writer_child(lock_path, attempted_path, acquired_path):
    write_status(attempted_path, "attempting")
    started = time.monotonic()
    try:
        with acquire_runtime_write_lock(
            path=lock_path,
            context="waiting_child",
            wait=True,
            timeout_seconds=5,
            poll_seconds=0.02,
        ):
            write_status(acquired_path, json.dumps({"elapsed": time.monotonic() - started}))
    except Exception as exc:
        write_status(acquired_path, f"error:{type(exc).__name__}:{exc}")


def timeout_writer_child(lock_path, status_path):
    started = time.monotonic()
    try:
        with acquire_runtime_write_lock(
            path=lock_path,
            context="timeout_child",
            wait=True,
            timeout_seconds=0.25,
            poll_seconds=0.02,
        ):
            write_status(status_path, "acquired")
    except RuntimeWriteLockError:
        write_status(status_path, json.dumps({"timeout": time.monotonic() - started}))
    except Exception as exc:
        write_status(status_path, f"error:{type(exc).__name__}:{exc}")


def crash_holder_child(lock_path, status_path):
    lock = acquire_runtime_write_lock(path=lock_path, context="crash_child")
    write_status(status_path, "locked")
    os._exit(0)


def concurrent_writers_fail_cleanly():
    final_path, lock_path = scratch_paths("contention")
    first_status_path = final_path.with_suffix(".first.status")
    second_status_path = final_path.with_suffix(".second.status")
    release_path = final_path.with_suffix(".release.status")
    cleanup(final_path, lock_path)
    cleanup(first_status_path, second_status_path, release_path)
    final_path.write_text(json.dumps({"writer": "original"}), encoding="utf-8")
    first = subprocess.Popen(
        [
            sys.executable,
            __file__,
            "--hold-lock",
            str(lock_path),
            str(final_path),
            str(first_status_path),
            str(release_path),
        ],
        cwd=ROOT,
    )
    try:
        first_status = wait_for_status(first_status_path)
        if first_status != "locked":
            return False
        second = subprocess.Popen(
            [
                sys.executable,
                __file__,
                "--try-write",
                str(lock_path),
                str(final_path),
                str(second_status_path),
            ],
            cwd=ROOT,
        )
        second_status = wait_for_status(second_status_path)
        owner_while_contended = read_lock(lock_path)
        write_status(release_path, "release")
        first.wait(timeout=10)
        second.wait(timeout=10)
        data = json.loads(final_path.read_text(encoding="utf-8"))
        return (
            second_status == "blocked"
            and int(owner_while_contended.get("pid", -1)) == first.pid
            and first.returncode == 0
            and second.returncode == 0
            and data == {"writer": "first"}
        )
    finally:
        for process in [locals().get("first"), locals().get("second")]:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        cleanup(final_path, lock_path, first_status_path, second_status_path, release_path)


def waiting_writer_acquires_only_after_release():
    final_path, lock_path = scratch_paths("waiting")
    holder_status = final_path.with_suffix(".holder.status")
    release_path = final_path.with_suffix(".release.status")
    attempted_path = final_path.with_suffix(".attempted.status")
    acquired_path = final_path.with_suffix(".acquired.status")
    cleanup(final_path, lock_path, holder_status, release_path, attempted_path, acquired_path)
    holder = subprocess.Popen([sys.executable, __file__, "--hold-lock", str(lock_path), str(final_path), str(holder_status), str(release_path)], cwd=ROOT)
    waiter = None
    try:
        if wait_for_status(holder_status) != "locked": return False
        waiter = subprocess.Popen([sys.executable, __file__, "--wait-write", str(lock_path), str(attempted_path), str(acquired_path)], cwd=ROOT)
        if wait_for_status(attempted_path) != "attempting": return False
        time.sleep(0.15)
        blocked_while_held = not acquired_path.exists() and int(read_lock(lock_path).get("pid", -1)) == holder.pid
        write_status(release_path, "release")
        holder.wait(timeout=10); waiter.wait(timeout=10)
        acquired = json.loads(acquired_path.read_text(encoding="utf-8"))
        return blocked_while_held and holder.returncode == 0 and waiter.returncode == 0 and 0.15 <= acquired["elapsed"] < 5
    finally:
        for process in (holder, waiter):
            if process is not None and process.poll() is None: process.terminate(); process.wait(timeout=5)
        cleanup(final_path, lock_path, holder_status, release_path, attempted_path, acquired_path)


def timeout_is_deterministic():
    final_path, lock_path = scratch_paths("timeout")
    holder_status = final_path.with_suffix(".holder.status"); release_path = final_path.with_suffix(".release.status")
    timeout_status = final_path.with_suffix(".timeout.status")
    cleanup(final_path, lock_path, holder_status, release_path, timeout_status)
    holder = subprocess.Popen([sys.executable, __file__, "--hold-lock", str(lock_path), str(final_path), str(holder_status), str(release_path)], cwd=ROOT)
    contender = None
    try:
        if wait_for_status(holder_status) != "locked": return False
        contender = subprocess.Popen([sys.executable, __file__, "--timeout-write", str(lock_path), str(timeout_status)], cwd=ROOT)
        result = wait_for_status(timeout_status); contender.wait(timeout=10)
        write_status(release_path, "release"); holder.wait(timeout=10)
        elapsed = json.loads(result)["timeout"]
        return contender.returncode == 0 and holder.returncode == 0 and 0.25 <= elapsed < 1.5
    finally:
        for process in (holder, contender):
            if process is not None and process.poll() is None: process.terminate(); process.wait(timeout=5)
        cleanup(final_path, lock_path, holder_status, release_path, timeout_status)


def stale_and_crashed_lock_recovery():
    final_path, lock_path = scratch_paths("crash")
    status_path = final_path.with_suffix(".status")
    cleanup(final_path, lock_path, status_path)
    child = subprocess.Popen([sys.executable, __file__, "--crash-lock", str(lock_path), str(status_path)], cwd=ROOT)
    try:
        if wait_for_status(status_path) != "locked": return False
        child.wait(timeout=10)
        with acquire_runtime_write_lock(path=lock_path, context="crash_recovery"):
            recovered = int(read_lock(lock_path).get("pid", -1)) == os.getpid()
        return child.returncode == 0 and recovered and not lock_path.exists()
    finally:
        if child.poll() is None: child.terminate(); child.wait(timeout=5)
        cleanup(final_path, lock_path, status_path)


def independent_lock_paths_do_not_serialize():
    first_path, first_lock = scratch_paths("independent_a")
    second_path, second_lock = scratch_paths("independent_b")
    cleanup(first_path, first_lock, second_path, second_lock)
    try:
        with acquire_runtime_write_lock(path=first_lock, context="independent_a"):
            with acquire_runtime_write_lock(path=second_lock, context="independent_b"):
                return first_lock.exists() and second_lock.exists()
    finally:
        cleanup(first_path, first_lock, second_path, second_lock)


def lock_released_after_exception():
    final_path, lock_path = scratch_paths("exception")
    cleanup(final_path, lock_path)
    final_path.write_text(json.dumps({"state": "original"}), encoding="utf-8")

    def fail_after_temp(stage, _target):
        if stage == "after_temp_write":
            raise RuntimeError("simulated failure")

    try:
        try:
            atomic_write_json(
                {"state": "failed"},
                final_path,
                failure_hook=fail_after_temp,
                lock_path=lock_path,
            )
        except Exception:
            pass

        atomic_write_json({"state": "after"}, final_path, lock_path=lock_path)
        return json.loads(final_path.read_text(encoding="utf-8")) == {"state": "after"}
    finally:
        cleanup(final_path, lock_path)


def nested_atomic_writes_do_not_deadlock():
    final_path, lock_path = scratch_paths("nested")
    csv_path = final_path.with_suffix(".csv")
    cleanup(final_path, csv_path, lock_path)

    try:
        with acquire_runtime_write_lock(path=lock_path, context="outer_lock"):
            atomic_write_json({"state": "nested"}, final_path, lock_path=lock_path)
            atomic_write_csv_frames(
                {csv_path: pd.DataFrame([{"state": "nested"}])},
                lock_path=lock_path,
            )
        return (
            json.loads(final_path.read_text(encoding="utf-8")) == {"state": "nested"}
            and pd.read_csv(csv_path).iloc[0]["state"] == "nested"
        )
    finally:
        cleanup(final_path, csv_path, lock_path)


def recovery_after_interrupted_locked_write():
    final_path, lock_path = scratch_paths("recovery")
    cleanup(final_path, lock_path)
    transaction_id = uuid4().hex
    temp = final_path.with_name(f".{final_path.name}.atomic-{transaction_id}.tmp")
    backup = final_path.with_name(f".{final_path.name}.atomic-{transaction_id}.bak")
    backup.write_text(json.dumps({"state": "old"}), encoding="utf-8")
    temp.write_text(json.dumps({"state": "new"}), encoding="utf-8")

    try:
        recover_atomic_artifacts(ROOT, lock_path=lock_path)
        return (
            json.loads(final_path.read_text(encoding="utf-8")) == {"state": "old"}
            and not temp.exists()
            and not backup.exists()
        )
    finally:
        cleanup(final_path, temp, backup, lock_path)


def atomic_io_uses_runtime_lock():
    source = (ROOT / "execution" / "atomic_io.py").read_text(encoding="utf-8")
    return (
        "acquire_runtime_write_lock" in source
        and "def atomic_write_csv_frames" in source
        and "def atomic_write_json" in source
        and "def recover_atomic_artifacts" in source
    )


def production_helpers_use_atomic_io():
    checks = {
        "execution/trade_ledger.py": [
            "def append_trade_events",
            "atomic_write_csv_frames({Path(path): updated})",
        ],
        "execution/broker_account.py": [
            "def save_account",
            "atomic_write_csv_frames({Path(ACCOUNT_FILE): account})",
        ],
        "execution/portfolio_manager.py": [
            "def save_portfolio",
            "def commit_trade_state",
            "atomic_write_csv_frames",
        ],
        "scripts/reconcile_ledger_open_lots.py": [
            "atomic_write_csv_frames({LEDGER_FILE: updated})",
            "atomic_write_json(report, REPORT_FILE)",
        ],
        "scripts/migrate_legacy_trade_history.py": [
            "atomic_write_csv_frames",
            "atomic_write_json(report, ROOT / REPORT_FILE)",
        ],
        "scripts/reconcile_broker_account.py": [
            "atomic_write_json(report, REPORT_FILE)",
        ],
        "reporting/paper_performance.py": [
            "atomic_write_csv_frames({Path(TRACKER_FILE): tracker})",
        ],
        "strategy/signals.py": [
            "atomic_write_csv_frames({\"fundamental_scores.csv\": fundamental_report})",
        ],
    }
    for relative_path, needles in checks.items():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        if not all(needle in source for needle in needles):
            return False
    return True


def no_leftover_lock_scratch_files():
    return not list(ROOT.glob("runtime_lock_*"))


def main():
    issues = []

    check(atomic_io_uses_runtime_lock(), "atomic IO routes through runtime write lock", issues)
    check(
        concurrent_writers_fail_cleanly(),
        "two concurrent writers cannot corrupt state; second fails cleanly",
        issues,
    )
    check(waiting_writer_acquires_only_after_release(), "waiting writer acquires only after holder releases", issues)
    check(timeout_is_deterministic(), "runtime write lock timeout is deterministic", issues)
    check(stale_and_crashed_lock_recovery(), "dead process locks are recovered safely", issues)
    check(independent_lock_paths_do_not_serialize(), "independent lock paths are not accidentally serialized", issues)
    check(
        lock_released_after_exception(),
        "runtime write lock is released after write exceptions",
        issues,
    )
    check(
        nested_atomic_writes_do_not_deadlock(),
        "nested atomic writes do not deadlock",
        issues,
    )
    check(
        recovery_after_interrupted_locked_write(),
        "recovery works after interrupted locked write",
        issues,
    )
    check(
        production_helpers_use_atomic_io(),
        "production write helpers route through atomic IO",
        issues,
    )
    check(
        no_leftover_lock_scratch_files(),
        "lock simulation leaves no scratch files",
        issues,
    )

    if issues:
        print("\nUnified runtime write lock validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nUnified runtime write lock validation passed.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--hold-lock":
        locked_writer_child(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
        sys.exit(0)
    if len(sys.argv) == 5 and sys.argv[1] == "--try-write":
        blocked_writer_child(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
        sys.exit(0)
    if len(sys.argv) == 5 and sys.argv[1] == "--wait-write":
        waiting_writer_child(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
        sys.exit(0)
    if len(sys.argv) == 4 and sys.argv[1] == "--timeout-write":
        timeout_writer_child(Path(sys.argv[2]), Path(sys.argv[3]))
        sys.exit(0)
    if len(sys.argv) == 4 and sys.argv[1] == "--crash-lock":
        crash_holder_child(Path(sys.argv[2]), Path(sys.argv[3]))
        sys.exit(0)
    sys.exit(main())
