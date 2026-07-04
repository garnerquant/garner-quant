from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

WRITER_EXPECTATIONS = {
    "execution/mark_to_market.py": [
        "broker_values_from_ledger_and_holdings",
        "broker_frame",
    ],
    "execution/portfolio_manager.py": [
        "broker_values_from_ledger_and_holdings",
        "update_account(",
    ],
    "runtime/live_runtime.py": [
        "reconcile_broker_account_file",
        "Broker Accounting Reconciled",
    ],
}

FORBIDDEN_PATTERNS = {
    "execution/mark_to_market.py": [
        "def _realised_pnl",
        "STARTING_CASH - float(original_position_value) + realised_pnl",
    ],
    "execution/portfolio_manager.py": [
        'realised_pnl = journal["pnl"].sum()',
        'realised_pnl = journal["pnl"].sum',
        'cash = STARTING_CASH - portfolio["position_value"].sum() + realised_pnl',
    ],
}


def check(condition, severity, message, issues):
    if condition:
        print(f"OK: {message}")
        return
    print(f"{severity}: {message}")
    issues.append((severity, message))


def main():
    issues = []
    print("Broker writer guard validation")

    for relative_path, expected_patterns in WRITER_EXPECTATIONS.items():
        path = ROOT / relative_path
        text = path.read_text(encoding="utf-8")
        for pattern in expected_patterns:
            check(
                pattern in text,
                "CRITICAL",
                f"{relative_path} contains required broker guard pattern: {pattern}",
                issues,
            )

    for relative_path, forbidden_patterns in FORBIDDEN_PATTERNS.items():
        path = ROOT / relative_path
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            check(
                pattern not in text,
                "CRITICAL",
                f"{relative_path} does not contain legacy broker formula: {pattern}",
                issues,
            )

    critical_or_high = [
        issue for issue in issues if issue[0] in {"CRITICAL", "HIGH"}
    ]
    print(
        "summary="
        + f"{len(issues)} issue(s), {len(critical_or_high)} critical/high issue(s)"
    )
    return 1 if critical_or_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
