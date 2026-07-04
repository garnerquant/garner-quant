from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.trade_reports import read_legacy_journal, write_authoritative_trade_reports


AUDIT_FILE = ROOT / "trade_audit_trail.csv"
ANALYTICS_FILE = ROOT / "trade_analytics_v3.csv"
JOURNAL_FILE = ROOT / "trade_journal_v3.csv"
LEDGER_FILE = ROOT / "trade_ledger_v1.csv"


def main():
    legacy_journal = read_legacy_journal(JOURNAL_FILE)
    audit, analytics = write_authoritative_trade_reports(
        legacy_journal=legacy_journal,
        audit_path=AUDIT_FILE,
        analytics_path=ANALYTICS_FILE,
        ledger_path=LEDGER_FILE,
    )

    print(f"audit_source={analytics.get('source', 'unknown')}")
    print(f"closed_trades={analytics.get('closed_trades', 0)}")
    print(f"open_positions={analytics.get('open_positions', 0)}")
    print(f"audit_rows={len(audit)}")
    print(f"wrote={AUDIT_FILE.name}")
    print(f"wrote={ANALYTICS_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
