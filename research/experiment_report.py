from __future__ import annotations

import json
from pathlib import Path

from execution.atomic_io import atomic_write_json
from research.experiment_metrics import METRIC_KEYS
from research.research_result_schema import (
    canonical_from_experiment_result,
    write_canonical_result,
)


DEFAULT_REPORT_DIR = Path("research") / "report_exports"


def format_value(value):
    if isinstance(value, int):
        return str(value)
    try:
        numeric = float(value)
    except Exception:
        return str(value)
    return f"{numeric:.6f}"


def metric_table(metrics):
    lines = ["| Metric | Value |", "| --- | ---: |"]
    for key in METRIC_KEYS:
        lines.append(f"| {key} | {format_value(metrics.get(key, 0))} |")
    return "\n".join(lines)


def delta_table(baseline, candidate, deltas):
    lines = ["| Metric | Baseline | Candidate | Delta |", "| --- | ---: | ---: | ---: |"]
    for key in METRIC_KEYS:
        lines.append(
            "| "
            f"{key} | {format_value(baseline.get(key, 0))} "
            f"| {format_value(candidate.get(key, 0))} "
            f"| {format_value(deltas.get(key, 0))} |"
        )
    return "\n".join(lines)


def build_markdown_report(result):
    comparison = result["comparison"]
    improved = comparison.get("improved_metrics", [])
    regressed = comparison.get("regressed_metrics", [])
    unchanged = comparison.get("unchanged_metrics", [])

    observations = [
        f"Improved metrics: {len(improved)}",
        f"Regressed metrics: {len(regressed)}",
        f"Unchanged/neutral metrics: {len(unchanged)}",
        (
            "Candidate and baseline metrics are identical within tolerance."
            if not improved and not regressed
            else "Candidate differs from baseline; review metric deltas before promotion."
        ),
    ]

    return "\n\n".join(
        [
            f"# Experiment {result['experiment_id']}",
            "## Summary\n"
            f"- Description: {result['description']}\n"
            f"- Date: {result['date']}\n"
            f"- Baseline: {result['baseline']['name']}\n"
            f"- Candidate: {result['candidate']['name']}\n"
            f"- Decision: {result['decision']}",
            "## Baseline Metrics\n" + metric_table(result["baseline"]["metrics"]),
            "## Candidate Metrics\n" + metric_table(result["candidate"]["metrics"]),
            "## Metric Deltas\n"
            + delta_table(
                result["baseline"]["metrics"],
                result["candidate"]["metrics"],
                comparison["deltas"],
            ),
            "## Improved Metrics\n"
            + ("\n".join(f"- {key}" for key in improved) if improved else "- None"),
            "## Regressed Metrics\n"
            + ("\n".join(f"- {key}" for key in regressed) if regressed else "- None"),
            "## Statistical Observations\n"
            + "\n".join(f"- {line}" for line in observations),
            "## Recommendation\n" + result["decision"],
        ]
    ) + "\n"


def write_experiment_reports(result, report_dir=DEFAULT_REPORT_DIR):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    base = report_dir / result["experiment_id"]
    markdown_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")

    markdown_path.write_text(build_markdown_report(result), encoding="utf-8")
    atomic_write_json(result, json_path)
    canonical_path = write_canonical_result(
        canonical_from_experiment_result(result),
        base_dir=report_dir / "canonical_results",
    )

    return {
        "markdown": str(markdown_path),
        "json": str(json_path),
        "canonical": canonical_path,
    }


def load_json_report(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
