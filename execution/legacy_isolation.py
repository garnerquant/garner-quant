from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os


LEGACY_SANDBOX_DIR = Path("data") / "legacy_sandbox"


class LegacyExecutionError(RuntimeError):
    pass


def legacy_refusal_message(entrypoint: str) -> str:
    return (
        f"{entrypoint} is a deprecated legacy execution path and is not allowed "
        "to write runtime state. Use main_v2.py/runtime.live_runtime for "
        "production, or rerun with --legacy-sandbox to isolate legacy outputs "
        "under data/legacy_sandbox."
    )


def require_legacy_sandbox(enabled: bool, entrypoint: str) -> None:
    if not enabled:
        raise LegacyExecutionError(legacy_refusal_message(entrypoint))


@contextmanager
def legacy_sandbox(entrypoint: str, sandbox_dir=LEGACY_SANDBOX_DIR):
    sandbox = Path(sandbox_dir)
    sandbox.mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    try:
        os.chdir(sandbox)
        yield sandbox
    finally:
        os.chdir(previous_cwd)
