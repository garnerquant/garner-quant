from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .models import EvidenceRecord, ReadOnlyEvidenceResponse, SnapshotFreshness

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path("/data/snapshots")
CONFIG_ROOT = Path("/data/config")
RESEARCH_ROOT = Path("/data/research")
MANIFEST_PATH = Path("/data/audit/baseline_evidence_manifest.json")
FRESHNESS_SECONDS = 36 * 60 * 60


def _iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)


def _freshness(generated: datetime, source: datetime | None) -> SnapshotFreshness:
    if source is None or generated < source:
        return SnapshotFreshness(source_as_of_utc=source, snapshot_age_seconds=None, freshness_threshold_seconds=FRESHNESS_SECONDS, status="unavailable")
    age = int((generated - source).total_seconds())
    return SnapshotFreshness(source_as_of_utc=source, snapshot_age_seconds=age, freshness_threshold_seconds=FRESHNESS_SECONDS, status="stale" if age > FRESHNESS_SECONDS else "fresh")


def response(version: str, records: list[EvidenceRecord], provenance: list[str], warnings: list[str], generated_at: datetime | None = None) -> ReadOnlyEvidenceResponse:
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    dates = [item.as_of_utc for item in records if item.as_of_utc is not None]
    source = max(dates) if dates else None
    classification = "unavailable" if not records else ("partial" if warnings else "local_snapshot")
    return ReadOnlyEvidenceResponse(schema_version=version, generated_at_utc=generated, source_as_of_utc=source, source_classification=classification, freshness=_freshness(generated, source), provenance=provenance, warnings=warnings, records=records)


def signals(generated_at: datetime | None = None, data_root: Path = DATA_ROOT) -> ReadOnlyEvidenceResponse:
    path = data_root / "signal_report_v2.csv"
    provenance = ["signal_report_v2.csv", "Rows must share one latest timestamp; required fields: timestamp, ticker, status, signal_code, target_weight."]
    if not path.is_file():
        return response("signals.v1", [], provenance, ["Signal snapshot is unavailable; no values are inferred."], generated_at)
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        aliases = {"timestamp": ("timestamp", "date", "as_of_utc"), "ticker": ("ticker", "instrument"), "status": ("status",), "signal_code": ("signal_code", "signal"), "target_weight": ("target_weight",)}
        def value(row: dict[str, str], key: str) -> str:
            return next((row[name].strip() for name in aliases[key] if row.get(name, "").strip()), "")
        parsed = [(_iso_datetime(value(row, "timestamp")), row) for row in rows]
        latest = max(item[0] for item in parsed)
        selected = [EvidenceRecord(identity=value(row, "ticker"), as_of_utc=stamp, status=value(row, "status"), fields={"signal_code": value(row, "signal_code"), "target_weight": value(row, "target_weight")}) for stamp, row in parsed if stamp == latest and all(value(row, key) for key in aliases)]
        if not selected or len({item.identity for item in selected}) != len(selected):
            raise ValueError("latest snapshot is incomplete or contains duplicate instruments")
        return response("signals.v1", sorted(selected, key=lambda item: item.identity), provenance, [], generated_at)
    except (ValueError, OSError, csv.Error) as exc:
        return response("signals.v1", [], provenance, [f"Signal snapshot rejected: {exc}."], generated_at)


def markets(generated_at: datetime | None = None, data_root: Path = DATA_ROOT) -> ReadOnlyEvidenceResponse:
    """Market bars remain unavailable until a mounted, timestamped snapshot has a defined schema."""
    return response("markets.v1", [], ["No validated market-bar snapshot is mounted.", "Currency, price unit, and completed-bar evidence are mandatory."], ["Validated market data is unavailable; the candlestick preview is not presented as API evidence."], generated_at)


def research(generated_at: datetime | None = None, research_root: Path = RESEARCH_ROOT) -> ReadOnlyEvidenceResponse:
    provenance = ["continuous_research/morning_reports/*/manifest.json", "Manifest metadata only; no performance or benchmark values are exposed."]
    records: list[EvidenceRecord] = []
    warnings: list[str] = []
    for path in sorted(research_root.glob("*/manifest.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            required = ("report_id", "created_at", "schema_version", "content_hash", "evidence_snapshot_id")
            if not all(isinstance(item.get(key), str) and item[key] for key in required):
                raise ValueError("required provenance is missing")
            created = _iso_datetime(item["created_at"])
            records.append(EvidenceRecord(identity=item["report_id"], as_of_utc=created, status="unverified", fields={"dataset": item["evidence_snapshot_id"], "schema_version": item["schema_version"], "content_hash": item["content_hash"], "strategy": None, "parameters": None, "execution_model": None, "cost_model": None, "information_cutoff": None, "code_version": None}))
        except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
            warnings.append(f"Rejected {path.name}: {exc}.")
    if not records:
        warnings.append("No reproducible research manifests are available.")
    elif any(value is None for item in records for value in item.fields.values()):
        warnings.append("Runs are unverified because reproducibility metadata is incomplete.")
    return response("research.v1", records, provenance, warnings, generated_at)


def shadow_runs(generated_at: datetime | None = None) -> ReadOnlyEvidenceResponse:
    return response("shadow-runs.v1", [], ["Manual decoder and runner outputs are not mounted in the dashboard API.", "The API cannot accept input, access browser files, run comparisons, or export results."], ["No immutable shadow comparison result is available for read-only display."], generated_at)


def risk_health(generated_at: datetime | None = None, config_root: Path = CONFIG_ROOT) -> ReadOnlyEvidenceResponse:
    provenance = ["live_runtime_config.json and risk_config.json (explicit read-only mounts)", "Only safety defaults are exposed; risk limits and mutation controls are excluded."]
    health_warnings = [
        "Quote freshness is stale or unavailable; current quotes cannot be confirmed.",
        "Research evidence remains unverified or unavailable.",
        "Source provenance is unavailable for one or more dashboard datasets.",
    ]
    try:
        runtime_path, risk_path = config_root / "live_runtime_config.json", config_root / "risk_config.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8")); risk = json.loads(risk_path.read_text(encoding="utf-8"))
        expected = {"mode": "monitor_only", "paper_execution_enabled": False, "trading_enabled": False, "limits_approved": False}
        actual = {"mode": runtime.get("mode"), "paper_execution_enabled": runtime.get("paper_execution_enabled"), "trading_enabled": risk.get("trading_enabled"), "limits_approved": risk.get("limits_approved")}
        if actual != expected:
            return response("risk-health.v1", [], provenance, ["Safety evidence differs from required fail-closed defaults.", *health_warnings], generated_at)
        as_of = datetime.fromtimestamp(max(runtime_path.stat().st_mtime, risk_path.stat().st_mtime), UTC)
        fields = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in actual.items()}
        fields.update({"heartbeat": None, "data_quality": None})
        return response("risk-health.v1", [EvidenceRecord(identity="safety-defaults", as_of_utc=as_of, status="monitor_only", fields=fields)], provenance, [
            "Heartbeat and data-quality evidence are unavailable; health fails closed.",
            *health_warnings,
        ], generated_at)
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return response("risk-health.v1", [], provenance, [f"Safety status is unavailable: {exc}.", *health_warnings], generated_at)


def audit(generated_at: datetime | None = None, manifest_path: Path = MANIFEST_PATH, repository_root: Path | None = None) -> ReadOnlyEvidenceResponse:
    provenance = ["baseline_evidence_manifest.json", "SHA-256 is recomputed read-only; immutable and mutable classifications retain distinct drift semantics."]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("artifact inventory is missing")
        records: list[EvidenceRecord] = []
        warnings: list[str] = []
        for item in sorted(artifacts, key=lambda value: str(value.get("relative_path", ""))):
            relative = item.get("relative_path"); expected = item.get("sha256"); mutability = item.get("mutability")
            if not all(isinstance(value, str) and value for value in (relative, expected, mutability)) or ".." in Path(relative).parts:
                warnings.append("A malformed or unsafe manifest entry was redacted."); continue
            if repository_root is not None:
                source = repository_root / relative
            elif relative.startswith("data/continuous_research/morning_reports/"):
                source = RESEARCH_ROOT / relative.removeprefix("data/continuous_research/morning_reports/")
            else:
                source = Path("/nonexistent")
            actual = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
            status = "verified" if actual == expected else ("drift" if actual and mutability == "mutable_runtime_state" else "unavailable" if actual is None else "mismatch")
            records.append(EvidenceRecord(identity=relative, status=status, fields={"classification": str(item.get("artifact_category", "unclassified")), "mutability": mutability, "expected_sha256": expected, "actual_sha256": actual, "modified_timestamp_utc": str(item.get("modified_timestamp_utc")) if item.get("modified_timestamp_utc") else None}))
        if any(item.status in {"mismatch", "unavailable"} for item in records): warnings.append("One or more immutable or mounted artifact checks could not be verified.")
        if any(item.status == "drift" for item in records): warnings.append("Mutable runtime drift is reported separately and is not treated as immutable corruption.")
        return response("audit.v1", records, provenance, warnings, generated_at)
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return response("audit.v1", [], provenance, [f"Audit manifest is unavailable: {exc}."], generated_at)
