from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(value, label, issues):
    print(("PASS" if value else "FAIL") + ": " + label)
    if not value: issues.append(label)


def main():
    issues = []
    result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_operational_dashboard_presentation", "-q"], cwd=ROOT)
    check(result.returncode == 0, "focused operational presentation tests", issues)
    helper_path = ROOT / "dashboard/operations_presentation.py"
    helper = helper_path.read_text(encoding="utf-8"); tree = ast.parse(helper)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    check(not any(name and name.startswith(("execution", "canonical_accounting", "runtime", "risk_engine")) for name in imports),
          "presentation helper has no trading, accounting, runtime, scheduler, risk, or persistence dependency", issues)
    check(all(token not in helper for token in ("write_text", "write_bytes", "to_csv", "submit_order", "publish_prepared")),
          "presentation helper is pure and read-only", issues)
    main_source = (ROOT / "web_dashboard.py").read_text(encoding="utf-8")
    operations = (ROOT / "pages/99_admin_health.py").read_text(encoding="utf-8")
    check("home_source_rows(HOME_SOURCE_DETAILS)" in main_source and "Per-instrument status" in main_source,
          "home sources and instrument status use compact tables", issues)
    check(all(label in main_source for label in ("Accounting Status", "Opening Evidence", "Critical Gaps", "Pending Reviews", "Evidence Coverage")),
          "accounting summary cards retain required information", issues)
    check("ops-card-context" in main_source and "font-size:20px" in main_source and "Not available" in helper,
          "accounting cards use quiet labels, prominent values, context, and safe missing-value wording", issues)
    check(all(label in main_source for label in ("Trading", "Runtime", "Research", "Notifications")),
          "latest activity is divided into four operational cards", issues)
    check(all(token in main_source for token in ("ops-green", "ops-blue", "ops-amber", "ops-red", "ops-grey")),
          "standard semantic status palette is present", issues)
    check('"execution_blocked": ("Execution disabled", "grey"' in helper and
          '"conflict": ("Conflict", "red"' in helper and '"no_action": ("No action", "blue"' in helper,
          "monitor-only, conflict, and no-action statuses use correct semantics", issues)
    check(all(text in main_source for text in ("Accounting status shows", "Opening evidence supports", "Evidence coverage is", "Buying power is", "Pending reviews are", "Monitor Mode")),
          "concise operational tooltips cover requested concepts", issues)
    check("<th scope=" in helper and "aria-label" in helper and "data-label" in helper,
          "tables and badges include accessible labels and responsive cell metadata", issues)
    check("padding:6px 10px" in main_source and "row_height=36" in operations,
          "main and Operations tables use compact readable row density", issues)
    check("ops-section-heading" in main_source and "margin:8px 0 4px 0" in main_source,
          "major dashboard sections use scoped compact spacing", issues)
    check("@media (max-width: 768px)" in main_source and "@media (max-width: 480px)" in main_source and
          "content:attr(data-label)" in main_source,
          "tablet and mobile breakpoints retain stacked labelled tables and cards", issues)
    check("Buying power is" in main_source and "Pending reviews are" in main_source and
          "Execution is disabled because" in helper,
          "requested tooltips remain concise and keyboard accessible", issues)
    check("investor_cycle_details" in main_source and '"Strategy scan skipped", "Monitor-only protection"' in main_source,
          "Latest Activity separates concise event and context", issues)
    check("st.write({" not in operations and "responsive_table" in operations,
          "Operations dense mappings are replaced with readable tables", issues)
    changed_domains = ("execution/", "runtime/", "canonical_accounting/", "risk_engine/")
    status = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True).stdout
    check(not any(domain in status.replace("\\", "/") for domain in changed_domains),
          "working changes contain no trading, accounting, risk, or runtime modules", issues)
    if issues: raise SystemExit("Operational dashboard UX validation failed: " + "; ".join(issues))
    print("Operational dashboard UX presentation validation passed.")


if __name__ == "__main__": main()
