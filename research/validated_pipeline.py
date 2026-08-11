"""Offline validated research orchestration and isolated evidence publication."""

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import hashlib
import json
import os
import tempfile
import stat

from data.point_in_time import FundamentalObservation
from research.evidence_mode import FieldRequirement, EvidenceModeDecision, select_evidence
from research.run_manifest import ResearchRunManifest, manifest_sha256
from research.technical_only import run_technical_only
from research.universe_selection import UniverseSelectionDecision, select_research_universe
from research.validated_dataset import ValidatedResearchDataset


PROTECTED_FILES = {"trade_log.csv", "fundamental_scores.csv", "portfolio_v2.csv", "holdings_report.csv", "paper_30_day_tracker.csv"}
REPO_ROOT = Path(__file__).parents[1].resolve()


@dataclass(frozen=True, slots=True)
class ValidatedResearchBundle:
    schema_version: int
    run_manifest: ResearchRunManifest
    run_manifest_hash: str
    dataset_hash: str
    universe_selection: UniverseSelectionDecision
    evidence_policy_id: str
    evidence_policy_version: str
    decision_records: tuple[dict, ...]
    exclusions: tuple[tuple[str, str], ...]
    result_classification: str
    warnings: tuple[str, ...]

    def payload(self):
        return {"schema_version": self.schema_version, "run_manifest_hash": self.run_manifest_hash, "dataset_hash": self.dataset_hash, "universe_selection_hash": self.universe_selection.canonical_sha256(), "evidence_policy_id": self.evidence_policy_id, "evidence_policy_version": self.evidence_policy_version, "decision_records": list(self.decision_records), "exclusions": [list(x) for x in self.exclusions], "result_classification": self.result_classification, "warnings": list(self.warnings)}

    def canonical_bytes(self):
        return json.dumps({"contract_type": "validated_research_bundle", "schema_version": 1, "payload": self.payload()}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    def bundle_hash(self): return hashlib.sha256(self.canonical_bytes()).hexdigest()


def assemble_validated_research(*, dataset: ValidatedResearchDataset, memberships, universe_id, universe_version, decision_date, information_cutoff, evidence_mode, evidence_policy_id, evidence_policy_version, strategy_id, strategy_version, parameter_set_id, code_revision, created_at, instrument_metadata_identity, benchmark_instrument, benchmark_currency_policy, execution_model_version, cost_model_version, fundamental_observations=(), fundamental_requirements=(), metadata_records=None, corporate_actions=(), run_id=""):
    if not run_id: raise ValueError("run_id is required")
    selection = select_research_universe(dataset=dataset, universe_id=universe_id, universe_version=universe_version, decision_date=decision_date, information_cutoff=information_cutoff, memberships=tuple(memberships), metadata_records=metadata_records, corporate_actions=tuple(corporate_actions))
    manifest = ResearchRunManifest(1, run_id, created_at, strategy_id, strategy_version, parameter_set_id, universe_id, universe_version, information_cutoff, ((dataset.dataset_id, dataset.dataset_version, dataset.canonical_sha256()),), code_revision, instrument_metadata_identity, dataset.price_basis, benchmark_instrument, benchmark_currency_policy, execution_model_version, cost_model_version, fundamental_snapshot=("prospective", "caller-supplied") if fundamental_observations else None)
    decisions = []
    selected = set(selection.eligible_instrument_ids)
    for instrument in sorted(selected):
        bars = tuple(bar for bar in dataset.bars if bar.instrument_id == instrument)
        if evidence_mode == "technical_only_historical_v1":
            result = run_technical_only(mode=evidence_mode, bars=bars, information_cutoff_utc=information_cutoff, strategy_id=strategy_id, strategy_version=strategy_version, parameter_version=parameter_set_id, universe_version=universe_version, code_revision=code_revision)
            decisions.extend({"decision_id": d.decision_id, "decision_hash": __import__("strategy.serialization", fromlist=["canonical_sha256"]).canonical_sha256(d), "status": d.decision_status.value, "action": d.decision_action.value} for d in result.decisions)
        elif evidence_mode == "point_in_time_fundamental_v1":
            result = select_evidence(mode=evidence_mode, instrument_id=instrument, decision_timestamp=information_cutoff, information_cutoff=information_cutoff, observations=tuple(fundamental_observations), requirements=tuple(fundamental_requirements))
            decisions.append({"instrument_id": instrument, "mode": evidence_mode, "status": result.status, "decision_hash": result.canonical_sha256(), "selected_observation_ids": list(result.selected_observation_ids)})
        else:
            raise ValueError("unsupported evidence mode")
    return ValidatedResearchBundle(1, manifest, manifest_sha256(manifest), dataset.canonical_sha256(), selection, evidence_policy_id, evidence_policy_version, tuple(decisions), selection.excluded_instrument_reasons, "exploratory_unverified", ("research-only", "non-production", "non-executable", "results unverified"))


def _file_hash(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_bundle(bundle: ValidatedResearchBundle, output_root) -> Path:
    root = Path(output_root).resolve()
    if not root.is_absolute() or REPO_ROOT == root or REPO_ROOT in root.parents:
        raise ValueError("publication output root must be outside the repository")
    namespace = root / bundle.run_manifest.run_id
    namespace.mkdir(parents=True, exist_ok=True)
    files = {"bundle.json": bundle.canonical_bytes()}
    manifest = {"schema_version": 1, "run_id": bundle.run_manifest.run_id, "files": [{"name": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()} for name, content in sorted(files.items())]}
    files["content_manifest.json"] = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    for name, content in files.items():
        target = namespace / name
        if target.exists() and target.read_bytes() != content: raise ValueError("publication namespace contains conflicting content")
        if not target.exists():
            fd, temp_name = tempfile.mkstemp(prefix=".research-", dir=namespace)
            try:
                with os.fdopen(fd, "wb") as handle: handle.write(content)
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name): os.unlink(temp_name)
    return namespace


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _safe_manifest_name(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("invalid publication path")
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if normalized.startswith(("/", "//")) or len(normalized) >= 2 and normalized[1] == ":":
        raise ValueError("absolute publication path")
    parts = normalized.split("/")
    if len(parts) != 1 or parts[0] in {"", ".", ".."}:
        raise ValueError("unsupported publication path")
    if path.is_absolute() or path.name != normalized:
        raise ValueError("unsupported publication path")
    return normalized


def _regular_entry(path):
    try:
        info = path.lstat()
    except (FileNotFoundError, OSError):
        return False
    return stat.S_ISREG(info.st_mode)


def verify_publication(namespace) -> bool:
    """Verify an exact, flat publication namespace without following links."""
    try:
        path = Path(namespace)
        if not path.is_dir() or path.is_symlink():
            return False
        manifest_path = path / "content_manifest.json"
        if not _regular_entry(manifest_path):
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("run_id"), str) or not isinstance(manifest.get("files"), list):
            return False
        expected = {}
        for item in manifest["files"]:
            if not isinstance(item, dict) or set(item) != {"name", "size", "sha256"}:
                return False
            name = _safe_manifest_name(item["name"])
            key = name.casefold()
            if key in expected:
                return False
            if not isinstance(item["size"], int) or isinstance(item["size"], bool) or item["size"] < 0:
                return False
            digest = item["sha256"]
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                return False
            expected[key] = (name, item["size"], digest)
        if set(expected) != {"bundle.json"}:
            return False
        actual = []
        for entry in path.iterdir():
            if entry.is_symlink() or not _regular_entry(entry):
                return False
            actual.append(entry.name)
        actual_keys = [name.casefold() for name in actual]
        if len(actual_keys) != len(set(actual_keys)) or set(actual_keys) != {"bundle.json", "content_manifest.json"}:
            return False
        target = path / expected["bundle.json"][0]
        size = expected["bundle.json"][1]
        digest = expected["bundle.json"][2]
        return target.stat().st_size == size and _file_hash(target) == digest
    except (OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return False
