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
INSTRUMENTS_PATH = Path("/data/instruments/current_assets.csv")
RUNTIME_STATUS_PATH = Path("/data/runtime/live_runtime_status.json")


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
    """Read the mounted monitor snapshot without making provider or runtime calls."""
    provenance = ["current_assets.csv + live_monitor_snapshot.json + live_runtime_status.json (explicit read-only mounts)", "Prices are displayed only when the per-instrument timestamp, provider, currency, and unit are present and valid.", "Freshness thresholds: exchange-traded 15 minutes; crypto 24 hours; future, missing, or stale values fail closed."]
    try:
        instruments_path = INSTRUMENTS_PATH
        snapshot_path = data_root / "live_monitor_snapshot.json"
        runtime_path = RUNTIME_STATUS_PATH
        if not instruments_path.is_file() or not snapshot_path.is_file():
            raise ValueError("instrument metadata or monitor snapshot is not mounted")
        with instruments_path.open(encoding="utf-8", newline="") as handle:
            instruments = list(csv.DictReader(handle))
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        prices = snapshot.get("latest_prices")
        if not isinstance(prices, dict):
            raise ValueError("latest_prices is missing")
        now = (generated_at or datetime.now(UTC)).astimezone(UTC)
        records: list[EvidenceRecord] = []
        warnings: list[str] = []
        for item in instruments:
            symbol = (item.get("yahoo_ticker") or "").strip()
            if not symbol:
                warnings.append("Instrument without provider symbol was excluded.")
                continue
            quote = prices.get(symbol)
            fields = {"name": item.get("name") or None, "asset_class": item.get("asset_class") or None, "exchange": item.get("exchange") or None, "currency": item.get("currency") or None, "price_unit": "per share" if item.get("asset_class") != "Crypto" else "per coin", "provider": "Yahoo Finance monitor snapshot", "price": None, "market_status": "unavailable", "freshness_threshold_seconds": "86400" if item.get("asset_class") == "Crypto" else "900"}
            status = "unavailable"
            as_of = None
            if isinstance(quote, dict) and quote.get("price") is not None and quote.get("timestamp"):
                try:
                    as_of = _iso_datetime(str(quote["timestamp"]))
                    threshold = 86400 if item.get("asset_class") == "Crypto" else 900
                    age = (now - as_of).total_seconds()
                    if as_of > now:
                        status = "unavailable"; warnings.append(f"{symbol} quote timestamp is in the future and was rejected.")
                    elif age > threshold:
                        status = "stale"; warnings.append(f"{symbol} quote is older than its {threshold}-second threshold.")
                    else:
                        status = "available"
                        fields["price"] = str(quote["price"])
                        fields["market_status"] = "available"
                except (TypeError, ValueError):
                    warnings.append(f"{symbol} quote timestamp is malformed and was rejected.")
            records.append(EvidenceRecord(identity=symbol, as_of_utc=as_of, status=status, fields=fields))
        if runtime_path.is_file():
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            open_markets = runtime.get("markets_open")
            if isinstance(open_markets, list):
                market_aliases = {"LSE": "LSE", "NASDAQ": "US", "NYSE": "US"}
                for record in records:
                    venue = market_aliases.get(record.fields.get("exchange") or "", record.fields.get("exchange"))
                    if venue not in open_markets and record.fields.get("asset_class") != "Crypto" and record.status == "available":
                        record.fields["market_status"] = "holiday/weekend"
        return response("markets.v1", records, provenance, warnings, generated_at)
    except (OSError, ValueError, json.JSONDecodeError, TypeError, csv.Error) as exc:
        return response("markets.v1", [], provenance, [f"Validated market data is unavailable; values were not inferred ({exc})."], generated_at)


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
    provenance = ["live_runtime_config.json, risk_config.json, and live_runtime_status.json (explicit read-only mounts)", "Runtime values are observations from the status artifact; counts are derived only from that artifact and are not execution outcomes.", "Heartbeat freshness threshold: 10 minutes; scheduler freshness threshold: 15 minutes. Missing lock, accounting, validation, or audit evidence is unavailable and requires operator review."]
    try:
        runtime_path, risk_path = config_root / "live_runtime_config.json", config_root / "risk_config.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8")); risk = json.loads(risk_path.read_text(encoding="utf-8"))
        expected = {"mode": "monitor_only", "paper_execution_enabled": False, "trading_enabled": False, "limits_approved": False}
        actual = {"mode": runtime.get("mode"), "paper_execution_enabled": runtime.get("paper_execution_enabled"), "trading_enabled": risk.get("trading_enabled"), "limits_approved": risk.get("limits_approved")}
        if actual != expected:
            return response("risk-health.v1", [], provenance, ["Safety evidence differs from required fail-closed defaults. Operator action: stop and review configuration before relying on dashboard evidence."], generated_at)
        now = (generated_at or datetime.now(UTC)).astimezone(UTC)
        as_of = datetime.fromtimestamp(max(runtime_path.stat().st_mtime, risk_path.stat().st_mtime), UTC)
        fields = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in actual.items()}
        fields.update({"heartbeat": None, "data_quality": None, "source_file": f"{runtime_path.name} + {risk_path.name}", "definition": "Configured safety controls; not an execution result.", "operator_action": "No action for controls; continue manual review before any mode change."})
        records = [EvidenceRecord(identity="safety-defaults", as_of_utc=as_of, status="observed", fields=fields)]
        warnings: list[str] = []
        runtime_candidates = [config_root / "live_runtime_status.json", RUNTIME_STATUS_PATH]
        status_path = next((path for path in runtime_candidates if path.is_file()), None)
        status = None
        if status_path:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        def add(identity: str, value: str | None, stamp: datetime | None, severity: str, source: str, definition: str, action: str) -> None:
            records.append(EvidenceRecord(identity=identity, as_of_utc=stamp, status=severity, fields={"value": value, "severity": severity, "source_file": source, "definition": definition, "operator_action": action}))
        if not isinstance(status, dict):
            warnings.append("Runtime status is missing; heartbeat, scheduler, failures, and validation outcomes are unavailable. Operator action: mount a validated read-only runtime status artifact.")
        else:
            def parsed(key: str) -> datetime | None:
                value = status.get(key)
                if not isinstance(value, str) or not value:
                    return None
                stamp = _iso_datetime(value)
                return stamp if stamp.tzinfo is not None and stamp <= now else None
            heartbeat = parsed("last_cycle_at")
            heartbeat_age = int((now - heartbeat).total_seconds()) if heartbeat else None
            hb_severity = "observed" if heartbeat_age is not None and heartbeat_age <= 600 else "stale" if heartbeat_age is not None else "unavailable"
            add("runtime-heartbeat", str(heartbeat_age) if heartbeat_age is not None else None, heartbeat, hb_severity, status_path.name, "Seconds since the last recorded runtime cycle; derived from generated_at and last_cycle_at.", "Investigate runtime status and scheduler logs before relying on the monitor." )
            add("last-successful-cycle", status.get("last_cycle_at") if heartbeat else None, heartbeat, "observed" if heartbeat else "unavailable", status_path.name, "Last cycle timestamp recorded by the runtime status artifact; success is not independently audited.", "Confirm a successful cycle in the runtime evidence before relying on freshness." )
            scheduler = status.get("strategy_scheduler") if isinstance(status.get("strategy_scheduler"), dict) else {}
            scheduler_stamp = heartbeat
            scheduler_health = scheduler.get("health") if isinstance(scheduler.get("health"), dict) else {}
            scheduler_value = scheduler_health.get("status") or ("failures present" if scheduler.get("decisions") and any(d.get("status", "").startswith("FAILED") for d in scheduler.get("decisions", []) if isinstance(d, dict)) else "unavailable")
            scheduler_age = int((now - scheduler_stamp).total_seconds()) if scheduler_stamp else None
            scheduler_severity = "observed" if scheduler_age is not None and scheduler_age <= 900 and not str(scheduler_value).startswith("fail") else "stale" if scheduler_age is not None and scheduler_age > 900 else "unavailable"
            add("scheduler-status", str(scheduler_value), scheduler_stamp, scheduler_severity, status_path.name, "Scheduler status recorded in the runtime status artifact; no scheduling is performed by the dashboard.", "Review scheduler failures and completed-bar evidence before relying on decisions." )
            add("scheduler-failures", str(sum(1 for d in scheduler.get("decisions", []) if isinstance(d, dict) and str(d.get("status", "")).startswith("FAILED"))), scheduler_stamp, "observed" if scheduler_stamp else "unavailable", status_path.name, "Count of FAILED decisions in the latest recorded scheduler output.", "Review each failed decision and its underlying market-data evidence." )
            add("lock-state", None, None, "unavailable", "not mounted", "Runtime lock state is not exposed to the read-only dashboard.", "Operator must inspect the runtime lock using the controlled operations procedure." )
            add("accounting-activation", None, None, "unavailable", "not mounted", "No accounting activation evidence is mounted; valuation fields do not prove accounting activation.", "Operator must verify canonical accounting activation separately; do not activate from the dashboard." )
            add("latest-validation", str(scheduler_health.get("status")) if scheduler_health.get("status") is not None else None, scheduler_stamp, "observed" if scheduler_stamp and scheduler_health else "unavailable", status_path.name, "Latest validation outcome recorded by the scheduler status; not an independent audit.", "Review validation evidence and rejected instruments before relying on outputs." )
            add("runtime-failure", status.get("last_error") or "none recorded", heartbeat, "warning" if status.get("last_error") else "observed", status_path.name, "Last runtime error field; absence means none was recorded, not that runtime health is proven.", "Investigate the recorded failure before continuing if a message is present." )
        if status_path:
            artifact_stamp = datetime.fromtimestamp(status_path.stat().st_mtime, UTC)
            artifact_age = int((now - artifact_stamp).total_seconds()) if artifact_stamp <= now else None
            add("runtime-artifact-freshness", str(artifact_age) if artifact_age is not None else None, artifact_stamp if artifact_age is not None else None, "observed" if artifact_age is not None and artifact_age <= 900 else "stale" if artifact_age is not None else "unavailable", status_path.name, "Seconds since the runtime status file was modified; file age does not prove the contents are current.", "Refresh and validate the mounted runtime artifact before relying on it." )
        else:
            add("runtime-artifact-freshness", None, None, "unavailable", "not mounted", "Runtime status file age cannot be established.", "Operator must mount the validated runtime status artifact." )
        add("data-source-integrity", None, None, "unavailable", "not mounted", "No independent data-source integrity evidence is mounted for runtime health.", "Operator must verify source completeness, provenance, and timestamp consistency." )
        add("evidence-integrity", None, None, "unavailable", "not mounted", "No independent audit result is mounted for runtime health.", "Operator must review the audit evidence before treating runtime values as verified." )
        warnings.extend(["Safety controls are observed configuration values, not proof that execution is possible or desirable.", "Data-source, lock, accounting activation, and independent audit evidence remain unavailable unless explicitly mounted."])
        return response("risk-health.v1", records, provenance, warnings, generated_at)
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return response("risk-health.v1", [], provenance, [f"Safety status is unavailable: {exc}. Operator action: mount and validate the runtime and risk configuration artifacts."], generated_at)


def audit(generated_at: datetime | None = None, manifest_path: Path = MANIFEST_PATH, repository_root: Path | None = None) -> ReadOnlyEvidenceResponse:
    provenance = ["baseline_evidence_manifest.json (explicit read-only mount)", "SHA-256 is recomputed read-only; immutable and mutable classifications retain distinct drift semantics.", "Validation and governance run outcomes are not inferred from documentation or artifact existence; absent mounted result artifacts remain unavailable."]
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
            records.append(EvidenceRecord(identity=relative, as_of_utc=_iso_datetime(str(item["modified_timestamp_utc"])) if item.get("modified_timestamp_utc") else None, status=status, fields={"classification": str(item.get("artifact_category", "unclassified")), "ownership": str(item.get("writer_authority", "unavailable")), "mutability": mutability, "source_path": relative, "expected_sha256": expected, "actual_sha256": actual, "severity": "info" if status == "verified" else "high", "definition": "Read-only SHA-256 comparison against the point-in-time baseline manifest.", "operator_action": "No action; retain immutable evidence." if status == "verified" else "Operator must restore or re-verify the artifact before relying on it.", "modified_timestamp_utc": str(item.get("modified_timestamp_utc")) if item.get("modified_timestamp_utc") else None}))
        if any(item.status in {"mismatch", "unavailable"} for item in records): warnings.append("One or more immutable or mounted artifact checks could not be verified.")
        if any(item.status == "drift" for item in records): warnings.append("Mutable runtime drift is reported separately and is not treated as immutable corruption.")
        required_domains = {
            "validation-run": "Mount a validation run result with workflow name, main branch, conclusion, commit, and completed timestamp.",
            "runtime-state-ownership": "Run the repository ownership validator and mount its result; do not infer ownership from file presence.",
            "source-runtime-separation": "Mount a validated source/runtime ownership result and review any drift.",
            "accounting-reconciliation": "Mount the read-only reconciliation report and verify its source timestamp and contract.",
            "evidence-pack": "Mount the frozen evidence-pack result and verify its hashes and cut-off.",
            "migration-governance": "Mount the migration approval/governance result and complete independent operator review.",
            "operator-review": "Mount the operator-review result with reviewer, timestamp, rationale, and supporting reference.",
            "frozen-evidence": "Mount the frozen-evidence validation result and verify the immutable bundle.",
            "acquisition-reconciliation": "Mount the acquisition/reconciliation result and resolve missing or conflicting evidence.",
        }
        for identity, action in required_domains.items():
            records.append(EvidenceRecord(identity=identity, status="unavailable", fields={"classification": "audit_result", "ownership": "unavailable", "mutability": "unavailable", "source_path": "not mounted", "severity": "high", "definition": "A validated result artifact for this audit domain is required; documentation or source code is not a result.", "operator_action": action}))
        warnings.append("Validation, ownership, reconciliation, evidence-pack, governance, and review result artifacts are not mounted; these domains are unavailable and not inferred.")
        return response("audit.v1", records, provenance, warnings, generated_at)
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return response("audit.v1", [], provenance, [f"Audit manifest is unavailable: {exc}."], generated_at)
