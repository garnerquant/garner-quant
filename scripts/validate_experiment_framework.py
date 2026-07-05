from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.experiment_metrics import METRIC_KEYS  # noqa: E402
from research.experiment_registry import load_registry  # noqa: E402
from research.experiment_runner import run_baseline_self_experiment  # noqa: E402
from research.experiment_report import load_json_report  # noqa: E402


SCRATCH = ROOT / "data" / "experiment_framework_validation"


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def prepare_scratch():
    shutil.rmtree(SCRATCH, ignore_errors=True)
    (SCRATCH / "reports").mkdir(parents=True, exist_ok=True)
    return SCRATCH / "registry.json", SCRATCH / "reports"


def run_pair():
    registry_path, report_dir = prepare_scratch()
    first = run_baseline_self_experiment(
        registry_path=registry_path,
        report_dir=report_dir,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    second = run_baseline_self_experiment(
        registry_path=registry_path,
        report_dir=report_dir,
        timestamp="2026-01-01T00:00:01+00:00",
    )
    return registry_path, first, second


def metrics_identical(first, second):
    return (
        first["baseline"]["metrics"] == first["candidate"]["metrics"]
        and second["baseline"]["metrics"] == second["candidate"]["metrics"]
        and first["baseline"]["metrics"] == second["baseline"]["metrics"]
    )


def reports_exist_and_parse(result):
    markdown = ROOT / result["reports"]["markdown"]
    json_path = ROOT / result["reports"]["json"]
    if not markdown.exists() or not json_path.exists():
        return False
    text = markdown.read_text(encoding="utf-8")
    data = load_json_report(json_path)
    return (
        "## Summary" in text
        and "## Baseline Metrics" in text
        and "## Candidate Metrics" in text
        and "## Recommendation" in text
        and data["experiment_id"] == result["experiment_id"]
    )


def registry_consistent(registry_path, first, second):
    registry = load_registry(registry_path)
    experiments = registry.get("experiments", [])
    ids = [item.get("experiment_id") for item in experiments]
    return (
        registry.get("version") == 1
        and len(experiments) == 2
        and len(ids) == len(set(ids))
        and first["experiment_id"] in ids
        and second["experiment_id"] in ids
        and all(item.get("report_location") for item in experiments)
    )


def baseline_result_shape(result):
    metrics = result["baseline"]["metrics"]
    return (
        set(METRIC_KEYS).issubset(metrics)
        and result["decision"] == "NEEDS MORE TESTING"
        and not result["comparison"]["improved_metrics"]
        and not result["comparison"]["regressed_metrics"]
    )


def framework_registry_exists():
    path = ROOT / "experiments" / "registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = [
        item.get("experiment_id")
        for item in data.get("experiments", [])
        if isinstance(item, dict)
    ]
    return (
        data.get("version") == 1
        and isinstance(data.get("experiments"), list)
        and len(ids) == len(set(ids))
    )


def main():
    issues = []
    registry_path, first, second = run_pair()

    check(framework_registry_exists(), "framework registry exists with unique IDs", issues)
    check(first["experiment_id"] != second["experiment_id"], "experiment IDs are unique", issues)
    check(metrics_identical(first, second), "baseline comparison is reproducible", issues)
    check(baseline_result_shape(first), "baseline self-comparison has complete neutral metrics", issues)
    check(reports_exist_and_parse(first), "reports generate correctly", issues)
    check(registry_consistent(registry_path, first, second), "registry stays consistent", issues)

    shutil.rmtree(SCRATCH, ignore_errors=True)

    if issues:
        print("\nExperiment framework validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nExperiment framework validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
