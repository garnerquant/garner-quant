from __future__ import annotations

import os
from pathlib import Path

import yfinance as yf


_configured = False


def configure_yfinance_cache_for_ci():
    """Keep yfinance's SQLite timezone cache private to one CI process."""
    global _configured
    if _configured or not os.getenv("CI"):
        return None

    root = Path(os.getenv("RUNNER_TEMP") or ".tmp")
    run = os.getenv("GITHUB_RUN_ID", "local-ci")
    attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    cache_dir = root / f"yfinance-cache-{run}-{attempt}-{os.getpid()}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache_dir))
    _configured = True
    return cache_dir
