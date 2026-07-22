"""Read-only dashboard adapter for immutable morning research reports."""
from pathlib import Path

from research.continuous_improvement.artifacts import load_latest_report_payload


def continuous_research_status(root: str | Path = "data/continuous_research"):
    payload = load_latest_report_payload(root)
    if payload is None:
        return {"status": "EMPTY", "report": None}
    return {"status": "PUBLISHED", "report": payload}
