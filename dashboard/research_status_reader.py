"""Read-only operator summaries for research reports and pipeline metadata."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from dashboard.research_report_reader import ResearchReportBundle

PIPELINE_STATES = frozenset({"IDLE", "RUNNING", "PUBLISHING", "COMPLETED", "FAILED", "UNAVAILABLE"})


@dataclass(frozen=True)
class ResearchPipelineStatus:
    status: str
    last_successful_run: str | None
    last_failed_run: str | None
    last_publication: str | None
    report_id: str | None
    message: str


def _count_candidates(bundle: ResearchReportBundle):
    frame = bundle.table("candidate_report.csv")
    required = {"group_value", "horizon_days", "observations"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    candidates = frame[frame["group_value"].astype(str).str.casefold().eq("candidate")].copy()
    if candidates.empty:
        return 0
    candidates["horizon_days"] = pd.to_numeric(candidates["horizon_days"], errors="coerce")
    candidates["observations"] = pd.to_numeric(candidates["observations"], errors="coerce")
    candidates = candidates.dropna(subset=["horizon_days", "observations"])
    if candidates.empty:
        return None
    earliest = candidates["horizon_days"].min()
    return int(candidates.loc[candidates["horizon_days"].eq(earliest), "observations"].max())


def research_report_overview(bundle: ResearchReportBundle) -> dict:
    manifest, summary = bundle.manifest, bundle.summary
    universe = summary.get("observation_count")
    generations = summary.get("generation_count", len(manifest.get("source_scanner_generations", ())))
    description = (f"Validated research across {universe} observations from {generations} scanner generation(s)."
                   if universe is not None else f"Validated research from {generations} scanner generation(s).")
    return {"publication_date": manifest.get("created_at"), "report_id": bundle.report_id,
            "universe_analysed": universe, "candidate_count": _count_candidates(bundle),
            "high_conviction_count": summary.get("high_conviction_count"), "summary": description,
            "status": str(manifest.get("status", "unknown")).upper()}


def read_research_pipeline_status(root: str | Path) -> ResearchPipelineStatus:
    """Read explicit manifest states only; absence remains unavailable."""
    generations = Path(root) / "generations"
    if not generations.is_dir():
        return ResearchPipelineStatus("UNAVAILABLE", None, None, None, None,
                                      "No research runtime or publication metadata is available.")
    records = []
    for path in generations.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            manifest = json.loads((path / "research_manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        raw = str(manifest.get("status", "")).strip().upper()
        status = {"COMPLETE": "COMPLETED"}.get(raw, raw)
        if status not in PIPELINE_STATES - {"UNAVAILABLE"}:
            continue
        records.append((str(manifest.get("created_at", "")), path.name, status))
    if not records:
        return ResearchPipelineStatus("UNAVAILABLE", None, None, None, None,
                                      "No usable research runtime or publication metadata is available.")
    records.sort(); latest = records[-1]
    successes = [row for row in records if row[2] == "COMPLETED"]
    failures = [row for row in records if row[2] == "FAILED"]
    return ResearchPipelineStatus(latest[2], successes[-1][0] if successes else None,
        failures[-1][0] if failures else None, successes[-1][0] if successes else None,
        successes[-1][1] if successes else None,
        "Research metadata was read from published report manifests.")
