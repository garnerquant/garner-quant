"""Offline and repository-write protections for the test suite."""

import builtins
import io
import os
import re
import socket
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NETWORK_ERROR = "Network access is disabled during tests"
WRITE_ERROR = "Repository writes are disabled during tests; use the approved temporary directory."

_CREDENTIAL_NAME = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY|SUPABASE|TELEGRAM|SMTP|"
    r"EMAIL_USERNAME|EMAIL_PASSWORD|AWS_|GITHUB_TOKEN|CODEX_ACCESS_TOKEN|OPENAI_API_KEY)",
    re.IGNORECASE,
)


def _inside_repository(value):
    if isinstance(value, int):
        return False
    try:
        candidate = Path(os.fspath(value)).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        candidate = candidate.resolve(strict=False)
        return candidate == REPOSITORY_ROOT or REPOSITORY_ROOT in candidate.parents
    except (OSError, TypeError, ValueError):
        return False


def _reject_repository_path(value):
    if _inside_repository(value):
        raise RuntimeError(WRITE_ERROR)


def isolate_credentials():
    for name in list(os.environ):
        if _CREDENTIAL_NAME.search(name):
            del os.environ[name]


def block_network(*_args, **_kwargs):
    raise RuntimeError(NETWORK_ERROR)


def install_safety_controls(monkeypatch):
    """Install deterministic, test-only network, credential and write guards."""
    isolate_credentials()

    monkeypatch.setattr(socket.socket, "connect", block_network)
    monkeypatch.setattr(socket.socket, "connect_ex", block_network)
    monkeypatch.setattr(socket, "create_connection", block_network)

    original_open = builtins.open
    original_io_open = io.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            _reject_repository_path(file)
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    def guarded_io_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            _reject_repository_path(file)
        return original_io_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(io, "open", guarded_io_open)

    original_os_open = os.open

    def guarded_os_open(file, flags, *args, **kwargs):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if flags & write_flags:
            _reject_repository_path(file)
        return original_os_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_os_open)

    for name in ("rename", "replace"):
        original = getattr(os, name)

        def guarded_move(src, dst, _original=original):
            _reject_repository_path(src)
            _reject_repository_path(dst)
            return _original(src, dst)

        monkeypatch.setattr(os, name, guarded_move)

    for name in ("remove", "unlink", "mkdir", "makedirs"):
        original = getattr(os, name)

        def guarded_path_mutation(path, *args, _original=original, **kwargs):
            _reject_repository_path(path)
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(os, name, guarded_path_mutation)
