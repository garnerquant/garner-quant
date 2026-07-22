"""Manual, advisory-only morning research report producer."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.continuous_improvement.artifacts import load_latest_report_payload, publish_morning_report
from research.continuous_improvement.evidence import build_evidence_snapshot
from research.continuous_improvement.workflow import build_morning_report


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None: raise argparse.ArgumentTypeError("timestamp must be timezone-aware")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description="Build one immutable advisory morning research report")
    parser.add_argument("--cutoff",required=True,type=timestamp); parser.add_argument("--created-at",required=True,type=timestamp)
    parser.add_argument("--root",type=Path,default=ROOT); parser.add_argument("--output",type=Path,default=ROOT/"data/continuous_research")
    args=parser.parse_args(argv)
    previous=load_latest_report_payload(args.output)
    snapshot=build_evidence_snapshot(args.root,cutoff=args.cutoff,created_at=args.created_at,
        predecessor_id=previous.get("evidence_snapshot_id") if previous else None)
    report=build_morning_report(snapshot,created_at=args.created_at,
        predecessor_id=previous.get("report_id") if previous else None,
        prior_hypotheses=tuple(previous.get("hypotheses", ())) if previous else ())
    path=publish_morning_report(report,args.output)
    print(f"Published advisory research report {report.report_id} at {path}")
    print(report.executive_summary)
    return 0


if __name__=="__main__": raise SystemExit(main())
