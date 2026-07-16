from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.atomic_io import atomic_write_csv_frames


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def main():
    issues = []
    source = (ROOT / "main_v2.py").read_text(encoding="utf-8")
    save_block = source.split('print("Saving CSV files...")', 1)[1].split(
        "ledger = load_trade_ledger()", 1
    )[0]
    check(
        '"paper_portfolio_v3.csv": paper_portfolio' not in save_block,
        "main does not rewrite the atomically committed paper portfolio",
        issues,
    )
    check(
        '"trade_journal_v3.csv": trade_journal' not in save_block,
        "main does not rewrite the atomically committed trade journal",
        issues,
    )

    scratch = ROOT / ".stale_post_commit_regression.csv"
    lock = ROOT / ".stale_post_commit_regression.lock"
    stale = pd.DataFrame(
        [{"ticker": "BTC-GBP", "shares": 0.0210814625594048}]
    )
    committed = pd.DataFrame(columns=["ticker", "shares"])
    try:
        atomic_write_csv_frames({scratch: committed}, lock_path=lock)
        atomic_write_csv_frames({scratch: stale}, lock_path=lock)
        recreated = pd.read_csv(scratch)
        check(
            len(recreated) == 1
            and abs(float(recreated.iloc[0]["shares"]) - 0.0210814625594048)
            <= 1e-12,
            "a redundant second save can recreate stale state after atomic commit",
            issues,
        )
    finally:
        scratch.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)

    callers = []
    for path in ROOT.rglob("*.py"):
        if (
            path.resolve() == Path(__file__).resolve()
            or any(part in {"venv", "__pycache__"} for part in path.parts)
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "update_portfolio(" in text and path.name != "portfolio_manager.py":
            callers.append(path.relative_to(ROOT).as_posix())
    check(callers == ["main_v2.py"], f"only audited caller is main_v2.py: {callers}", issues)

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
