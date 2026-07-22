"""Immutable publication and readback for advisory research artifacts only."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .models import json_value, stable_hash


def serialize_report(report):
    payload = json_value(asdict(report)); payload["content_hash"] = report.content_hash
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def publish_morning_report(report, root: str | Path):
    root = Path(root); destination = root / "morning_reports" / report.report_id
    if destination.exists(): raise FileExistsError("morning research report already exists")
    staging = root / "morning_reports" / f".{report.report_id}.{uuid4().hex}.tmp"
    staging.mkdir(parents=True)
    try:
        content = serialize_report(report).encode()
        (staging / "morning_report.json").write_bytes(content)
        manifest = {"artifact_type": "MORNING_RESEARCH_REPORT", "report_id": report.report_id,
                    "content_hash": report.content_hash, "file_hash": stable_hash(content.decode()),
                    "evidence_snapshot_id": report.evidence_snapshot_id, "evidence_snapshot_hash": report.evidence_snapshot_hash,
                    "created_at": report.created_at.isoformat(), "schema_version": report.schema_version}
        (staging / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(staging, destination); return destination
    except Exception:
        if staging.exists(): shutil.rmtree(staging, ignore_errors=True)
        raise


def load_latest_report_payload(root: str | Path):
    base = Path(root) / "morning_reports"
    if not base.is_dir(): return None
    valid = []
    for path in base.iterdir():
        if not path.is_dir() or path.name.startswith("."): continue
        try:
            raw = (path/"morning_report.json").read_text()
            manifest = json.loads((path/"manifest.json").read_text()); payload = json.loads(raw)
            if manifest["report_id"] != payload["report_id"] or manifest["content_hash"] != payload["content_hash"]: continue
            if manifest["file_hash"] != stable_hash(raw): continue
            if stable_hash({key:value for key,value in payload.items() if key != "content_hash"}) != payload["content_hash"]: continue
            valid.append((manifest["created_at"], path.name, payload))
        except (OSError, ValueError, KeyError, TypeError): continue
    return max(valid, default=(None,None,None))[2]
