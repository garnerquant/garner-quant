from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canonical_accounting.generation import build_cash_only_generation  # noqa: E402
from dashboard.accounting_reader import load_dashboard_accounting_status  # noqa: E402


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def main():
    issues = []
    scratch = ROOT / ".tmp" / "dashboard_accounting_status_validation"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        pending_root = scratch / "pending"
        pending_root.mkdir()
        before = list(pending_root.rglob("*"))
        pending = load_dashboard_accounting_status(pending_root)
        after = list(pending_root.rglob("*"))
        check(pending.state == "pending", "missing active generation is pending", issues)
        check(pending.bundle is None, "pending state exposes no canonical bundle", issues)
        check(before == after, "pending read creates no accounting files or pointer", issues)

        active_root = scratch / "active"
        generation_id = "fixture-generation"
        build_cash_only_generation(
            active_root / "generations" / generation_id,
            generation_id=generation_id,
            activated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            legacy_root=scratch,
        )
        (active_root / "accounting_generation.json").write_text(
            json.dumps({"generation_id": generation_id}), encoding="utf-8"
        )
        active_before = {path: path.read_bytes() for path in active_root.rglob("*") if path.is_file()}
        active = load_dashboard_accounting_status(active_root)
        active_after = {path: path.read_bytes() for path in active_root.rglob("*") if path.is_file()}
        check(active.state == "active", "verified generation is active", issues)
        check(active.bundle is not None and active.bundle.generation_id == generation_id,
              "active state comes from authoritative accounting bundle", issues)
        check(active.reason is None, "active state has no legacy warning detail", issues)
        check(active_before == active_after, "active dashboard read is read-only", issues)

        ledger = active_root / "generations" / generation_id / "trade_ledger_v2.csv"
        original_ledger = ledger.read_bytes()
        ledger.write_bytes(original_ledger + b"\n")
        corrupt_generation = load_dashboard_accounting_status(active_root)
        check(corrupt_generation.state == "error", "corrupt generation is an accounting error", issues)
        check(corrupt_generation.reason == "canonical artifact hash mismatch: trade_ledger_v2.csv",
              "generation error retains the reader's exact safe diagnostic", issues)
        ledger.write_bytes(original_ledger)

        pointer = active_root / "accounting_generation.json"
        pointer.write_text("{", encoding="utf-8")
        corrupt_before = pointer.read_bytes()
        error = load_dashboard_accounting_status(active_root)
        check(error.state == "error", "corrupt pointer is an accounting error", issues)
        check(error.reason == "no active canonical accounting generation",
              "corrupt pointer retains the reader's exact safe diagnostic", issues)
        check(pointer.read_bytes() == corrupt_before, "error path fails closed without writes", issues)

        source = (ROOT / "web_dashboard.py").read_text(encoding="utf-8")
        reader_source = (ROOT / "dashboard" / "accounting_reader.py").read_text(encoding="utf-8")
        check("ACCOUNTING: CANONICAL GENERATION PENDING" in source,
              "amber pending badge label is present", issues)
        check("ACCOUNTING: CANONICAL GBP ACTIVE" in source,
              "green active badge label is present", issues)
        check("ACCOUNTING: ERROR" in source, "red error badge label is present", issues)
        check("Legacy history is not currency-normalized and is excluded from canonical GBP totals." in source,
              "legacy explanation remains available", issues)
        check("accountingStatus.title = data.accountingDetail" in source
              and 'accountingStatus.tabIndex = 0' in source,
              "accounting detail is exposed as a keyboard-focusable tooltip", issues)
        check("Legacy nominal history \u2014" not in source and "st.warning(\n        \"Legacy" not in source,
              "full-width legacy warning banner is absent", issues)
        check('id="runtime-badge"' in source and 'id="freshness-badge"' in source,
              "runtime and data-recency badges remain present", issues)
        check(source.index('id="runtime-badge"') < source.index('id="freshness-badge"')
              < source.index('id="accounting-status"') < source.index('id="last-scan-label"'),
              "status strip retains the requested visual order", issues)
        check("load_dashboard_accounting_status()" in source
              and "load_dashboard_accounting(" not in source,
              "dashboard consumes the authoritative status reader without duplicating state logic", issues)
        check("to_csv" not in reader_source and "atomic_write" not in reader_source,
              "dashboard accounting reader remains read-only", issues)
        prohibited = ("ledger_accounting", "fifo_accounting", "convert_amount_to_base", "base_market_value")
        check(not any(token in source for token in prohibited),
              "dashboard performs no trading or accounting calculations", issues)
        check("build_equity_curve_layers" in source and "render_equity_curve" in source,
              "existing chart paths remain present", issues)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if issues:
        raise AssertionError("; ".join(issues))
    print("\nDashboard accounting-status validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
