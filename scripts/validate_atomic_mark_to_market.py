from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.atomic_io import assert_no_atomic_artifacts  # noqa: E402
from execution.mark_to_market import (  # noqa: E402
    BROKER_FILE,
    HOLDINGS_FILE,
    PORTFOLIO_FILE,
    PORTFOLIO_REPORT_FILE,
    TRACKER_FILE,
    _commit_refresh_frames,
)


MARK_TO_MARKET_FILES = [
    PORTFOLIO_FILE,
    HOLDINGS_FILE,
    BROKER_FILE,
    PORTFOLIO_REPORT_FILE,
    TRACKER_FILE,
]


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def scratch_paths(token):
    return {
        file_name: ROOT / f"atomic_mtm_{token}_{file_name}"
        for file_name in MARK_TO_MARKET_FILES
    }


def original_text(file_name):
    return f"marker,file\noriginal,{file_name}\n"


def write_originals(paths):
    for file_name, path in paths.items():
        path.write_text(original_text(file_name), encoding="utf-8")


def read_originals(paths):
    return {
        file_name: path.read_text(encoding="utf-8")
        for file_name, path in paths.items()
    }


def cleanup(paths):
    for path in paths.values():
        path.unlink(missing_ok=True)
        for artifact in ROOT.glob(f".{path.name}.atomic-*"):
            artifact.unlink(missing_ok=True)


def refresh_frames():
    portfolio = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "shares": 2.0,
                "entry_price": 50.0,
                "position_value": 100.0,
                "current_price": 60.0,
                "market_value": 120.0,
                "unrealised_pnl": 20.0,
                "unrealised_pnl_pct": 0.2,
                "valuation_updated_at": "2026-07-04 12:00:00",
            }
        ]
    )
    holdings = pd.DataFrame(
        [
            {
                "date": "2026-07-04 12:00:00",
                "ticker": "TEST",
                "shares": 2.0,
                "entry_price": 50.0,
                "current_price": 60.0,
                "market_value": 120.0,
                "unrealised_pnl": 20.0,
                "unrealised_pnl_percent": 0.2,
            }
        ]
    )
    broker = pd.DataFrame(
        [
            {
                "cash": 10000.0,
                "buying_power": 10000.0,
                "positions_value": 120.0,
                "portfolio_value": 10120.0,
                "realised_pnl": 0.0,
                "unrealised_pnl": 20.0,
            }
        ]
    )
    report = pd.DataFrame(
        [
            {
                "equity": 10120.0,
                "daily_return": 0.012,
                "peak": 10120.0,
                "drawdown": 0.0,
            }
        ]
    )
    tracker = pd.DataFrame(
        [
            {
                "date": "2026-07-04 12:00:00",
                "portfolio_value": 10120.0,
                "cash": 10000.0,
                "realised_pnl": 0.0,
                "unrealised_pnl": 20.0,
                "benchmark_return": 0.0,
                "alpha": 0.0,
            }
        ]
    )
    return {
        PORTFOLIO_FILE: portfolio,
        HOLDINGS_FILE: holdings,
        BROKER_FILE: broker,
        PORTFOLIO_REPORT_FILE: report,
        TRACKER_FILE: tracker,
    }


def simulate_failure(stage_to_fail):
    token = uuid4().hex
    paths = scratch_paths(token)
    write_originals(paths)
    before = read_originals(paths)
    replaced = 0

    def failure_hook(stage, _target):
        nonlocal replaced
        if stage_to_fail == "after_temp_writes" and stage == "after_temp_writes":
            raise RuntimeError("simulated temp barrier failure")
        if stage_to_fail == "after_first_replace" and stage == "after_replace":
            replaced += 1
            if replaced == 1:
                raise RuntimeError("simulated replace failure")

    try:
        try:
            _commit_refresh_frames(
                refresh_frames(),
                output_paths=paths,
                failure_hook=failure_hook,
            )
        except Exception:
            pass

        after = read_originals(paths)
        artifacts = [
            artifact
            for path in paths.values()
            for artifact in ROOT.glob(f".{path.name}.atomic-*")
        ]
        return before == after and not artifacts
    finally:
        cleanup(paths)


def production_files_parse():
    for file_name in MARK_TO_MARKET_FILES:
        path = ROOT / file_name
        if path.exists():
            pd.read_csv(path)
    return True


def mark_to_market_uses_atomic_commit():
    source = (ROOT / "execution" / "mark_to_market.py").read_text(encoding="utf-8")
    return "atomic_write_csv_frames" in source and ".to_csv(" not in source


def main():
    issues = []

    try:
        assert_no_atomic_artifacts(ROOT)
        no_artifacts = True
    except Exception as exc:
        print(exc)
        no_artifacts = False

    check(no_artifacts, "no unfinished atomic artifacts exist", issues)
    check(production_files_parse(), "mark-to-market CSV files are parseable", issues)
    check(
        mark_to_market_uses_atomic_commit(),
        "mark_to_market_refresh has no direct CSV write path",
        issues,
    )
    check(
        simulate_failure("after_temp_writes"),
        "temp-write failure leaves mark-to-market files unchanged",
        issues,
    )
    check(
        simulate_failure("after_first_replace"),
        "replace failure rolls back mark-to-market files",
        issues,
    )

    if issues:
        print("\nAtomic mark-to-market validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nAtomic mark-to-market validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
