from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import sys
import threading
import time
from uuid import uuid4


DEFAULT_EXECUTION_LOCK = Path("data") / "execution.lock"
DEFAULT_STALE_SECONDS = 6 * 60 * 60


class RuntimeWriteLockError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def iso_timestamp(value=None):
    value = value or utc_now()
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_timestamp(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def process_is_running(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False

    if pid <= 0:
        return False

    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            process_query_limited_information = 0x1000
            still_active = 259
            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if not handle:
                return False

            exit_code = ctypes.c_ulong()
            try:
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def lock_metadata(context=None):
    return {
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
        "created_at": iso_timestamp(),
        "command": " ".join(sys.argv),
        "context": context or "main_v2.main",
    }


def read_lock(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def lock_age_seconds(metadata):
    created_at = parse_timestamp(metadata.get("created_at"))
    if created_at is None:
        return None
    return max(0.0, (utc_now() - created_at).total_seconds())


class ExecutionLock(AbstractContextManager):
    def __init__(self, path, acquired, reason=None, existing=None):
        self.path = Path(path)
        self.acquired = bool(acquired)
        self.reason = reason
        self.existing = existing or {}
        self._released = False

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return False

    def release(self):
        if not self.acquired or self._released:
            return

        try:
            current = read_lock(self.path)
            if (
                int(current.get("pid", -1)) == os.getpid()
                and int(current.get("thread_id", -1)) == threading.get_ident()
            ):
                self.path.unlink(missing_ok=True)
        finally:
            self._released = True


class RuntimeWriteLock(AbstractContextManager):
    def __init__(self, lock=None, acquired=False, reason=None, existing=None):
        self.lock = lock
        self.acquired = bool(acquired)
        self.reason = reason
        self.existing = existing or {}

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return False

    def release(self):
        if self.lock is not None:
            self.lock.release()


def current_process_owns_lock(path=DEFAULT_EXECUTION_LOCK):
    metadata = read_lock(path)
    try:
        return (
            int(metadata.get("pid", -1)) == os.getpid()
            and int(metadata.get("thread_id", -1)) == threading.get_ident()
        )
    except (TypeError, ValueError):
        return False


def take_over_stale_lock(path):
    """Atomically reserve a stale lock before removing it."""
    stale_path = Path(path).with_name(f".{Path(path).name}.stale-{uuid4().hex}")
    try:
        Path(path).replace(stale_path)
    except FileNotFoundError:
        return False
    stale_path.unlink(missing_ok=True)
    return True


def acquire_execution_lock(
    path=DEFAULT_EXECUTION_LOCK,
    context=None,
    stale_seconds=DEFAULT_STALE_SECONDS,
):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = lock_metadata(context=context)

    while True:
        try:
            fd = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2)
            return ExecutionLock(path, True)
        except FileExistsError:
            existing = read_lock(path)
            existing_pid = existing.get("pid")
            age = lock_age_seconds(existing)
            pid_running = process_is_running(existing_pid)

            if not pid_running:
                if take_over_stale_lock(path):
                    print(
                        "Warning: stale execution lock taken over "
                        "(PID is not running)."
                    )
                    continue
                continue

            if age is not None and age > stale_seconds:
                print(
                    "Warning: stale execution lock taken over "
                    f"(age {int(age)}s exceeded {stale_seconds}s)."
                )
                if take_over_stale_lock(path):
                    continue
                continue

            return ExecutionLock(
                path,
                False,
                reason="another execution is already running",
                existing=existing,
            )


def acquire_runtime_write_lock(
    path=DEFAULT_EXECUTION_LOCK,
    context=None,
    stale_seconds=DEFAULT_STALE_SECONDS,
    wait=False,
    timeout_seconds=0,
    poll_seconds=0.1,
):
    path = Path(path)
    started = time.monotonic()

    while True:
        if current_process_owns_lock(path):
            return RuntimeWriteLock(acquired=True)

        lock = acquire_execution_lock(
            path=path,
            context=context or "runtime_write",
            stale_seconds=stale_seconds,
        )
        if lock.acquired:
            return RuntimeWriteLock(lock=lock, acquired=True)

        if not wait or (
            timeout_seconds is not None
            and timeout_seconds > 0
            and time.monotonic() - started >= timeout_seconds
        ):
            raise RuntimeWriteLockError(
                "runtime write lock is already held by another execution"
            )

        time.sleep(max(0.01, float(poll_seconds)))
