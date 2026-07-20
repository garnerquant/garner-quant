"""Read-only access to immutable Scanner research report generations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


REPORT_FILES = (
    "factor_report.csv",
    "sector_report.csv",
    "country_report.csv",
    "bucket_report.csv",
    "regime_report.csv",
    "candidate_report.csv",
    "ranking_report.csv",
)


class ResearchReportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchReportBundle:
    report_id: str
    path: Path
    manifest: dict
    summary: dict
    tables: dict[str, pd.DataFrame]

    def table(self, name: str) -> pd.DataFrame:
        frame = self.tables.get(name, pd.DataFrame())
        return frame.copy(deep=True)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResearchReportReader:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _generation_paths(self) -> list[Path]:
        base = self.root / "generations"
        if not base.is_dir():
            return []
        return sorted(
            (path for path in base.iterdir() if path.is_dir() and not path.name.startswith(".")),
            key=lambda path: path.name,
        )

    def load_latest(self) -> ResearchReportBundle | None:
        paths = self._generation_paths()
        if not paths:
            return None
        completed = []
        for path in paths:
            try:
                manifest = json.loads((path / "research_manifest.json").read_text(encoding="utf-8"))
                if manifest.get("status") == "complete":
                    completed.append((str(manifest.get("created_at", "")), path))
            except (OSError, ValueError, TypeError):
                continue
        if not completed:
            return None
        return self.load_report(max(completed, key=lambda item: (item[0], item[1].name))[1].name)

    def load_report(self, report_id: str) -> ResearchReportBundle:
        if not report_id or Path(report_id).name != report_id:
            raise ResearchReportError("Research report identity is invalid.")
        path = (self.root / "generations" / report_id).resolve()
        if path.parent != (self.root / "generations").resolve() or not path.is_dir():
            raise ResearchReportError("Research report generation is missing.")
        try:
            manifest = json.loads((path / "research_manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ResearchReportError("Research report manifest is invalid.") from exc
        if manifest.get("report_id") != report_id or manifest.get("status") != "complete":
            raise ResearchReportError("Research report is incomplete or has inconsistent identity.")
        hashes = manifest.get("hashes")
        if not isinstance(hashes, dict):
            raise ResearchReportError("Research report hashes are missing.")
        for name, expected in hashes.items():
            artifact = path / str(name)
            if not artifact.is_file() or _hash(artifact) != str(expected):
                raise ResearchReportError(f"Research report artifact validation failed: {name}")
        try:
            summary = json.loads((path / "research_summary.json").read_text(encoding="utf-8"))
            tables = {
                name: pd.read_csv(path / name)
                for name in REPORT_FILES
                if (path / name).is_file()
            }
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise ResearchReportError("Research report artifact is malformed.") from exc
        return ResearchReportBundle(report_id, path, dict(manifest), dict(summary), tables)
