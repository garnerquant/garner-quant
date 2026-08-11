"""External, operator-requested immutable evidence export for shadow results."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from research import shadow_runner as _shadow_runner


SCHEMA_VERSION = 1
_FILES = frozenset({"shadow_result.json", "export_metadata.json", "content_manifest.json"})
_DECLARED = frozenset({"shadow_result.json", "export_metadata.json"})
_REPO_ROOT = Path(__file__).parents[1].resolve()
_SHA256 = set("0123456789abcdef")
_MAX_TEXT = 4096
_MAX_EXPORT_ID = 128


def _sha(data): return hashlib.sha256(data).hexdigest()


def _utc(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")
    return value


def _text(value, name, maximum=_MAX_TEXT):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be bounded nonblank text")
    return value


def _digest(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(char not in _SHA256 for char in value):
        raise ValueError(f"{name} must be lowercase SHA-256")
    return value


def _export_id(value):
    value = _text(value, "export_id", _MAX_EXPORT_ID)
    if not all(char.isascii() and (char.isalnum() or char in "-_") for char in value):
        raise ValueError("export_id is unsafe")
    return value


def _regular(path):
    try: return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except OSError: return False


def _safe_name(value):
    if not isinstance(value, str) or value not in _DECLARED or Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError("unsafe manifest filename")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json_bytes(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _result_bytes(result):
    if not isinstance(result, _shadow_runner.ShadowRunResult): raise TypeError("result must be ShadowRunResult")
    if result.result_classification != _shadow_runner.RESULT_CLASSIFICATION: raise ValueError("result classification is inconsistent")
    if any(getattr(result, name) is not False for name in ("execution_authorized", "publication_authorized", "runtime_effect", "paper_effect", "accounting_effect")):
        raise ValueError("result safety fields are inconsistent")
    data = result.canonical_bytes()
    if _sha(data) != result.canonical_hash: raise ValueError("result hash does not match canonical content")
    return data


def build_export_metadata(*, result, export_id, created_at, operator_purpose, code_version, raw_input_sha256, canonical_input_sha256):
    """Build metadata only; this function performs no filesystem operation."""
    result_bytes = _result_bytes(result)
    created_at = _utc(created_at, "created_at")
    metadata = {
        "schema_version": SCHEMA_VERSION, "export_id": _export_id(export_id), "shadow_run_id": _text(result.shadow_run_id, "shadow_run_id"),
        "result_hash": _sha(result_bytes), "raw_input_sha256": _digest(raw_input_sha256, "raw_input_sha256"),
        "canonical_input_sha256": _digest(canonical_input_sha256, "canonical_input_sha256"),
        "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "operator_purpose": _text(operator_purpose, "operator_purpose"),
        "code_version": _text(code_version, "code_version"), "result_classification": result.result_classification,
        "execution_authorized": False, "publication_authorized": False, "runtime_effect": False, "paper_effect": False,
        "accounting_effect": False, "warnings": list(result.warnings), "limitations": list(result.limitations),
    }
    metadata["metadata_canonical_sha256"] = _sha(_json_bytes(metadata))
    return metadata


def canonical_export_sha256(metadata):
    """Return the canonical metadata hash, verifying any embedded metadata hash."""
    if not isinstance(metadata, dict): raise TypeError("metadata must be a mapping")
    value = dict(metadata); supplied = value.pop("metadata_canonical_sha256", None)
    digest = _sha(_json_bytes(value))
    if supplied is not None and supplied != digest: raise ValueError("metadata canonical hash is inconsistent")
    return digest


def _root(output_root):
    if output_root is None: raise ValueError("explicit output_root is required")
    root = Path(output_root)
    if not root.is_absolute() or not root.exists() or not root.is_dir() or root.is_symlink(): raise ValueError("output_root must be an existing non-link directory")
    resolved = root.resolve()
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents: raise ValueError("output_root must be outside repository")
    return resolved


def _contents(result, metadata):
    result_bytes = _result_bytes(result)
    metadata_bytes = _json_bytes(metadata)
    files = {"shadow_result.json": result_bytes, "export_metadata.json": metadata_bytes}
    manifest = {"schema_version": SCHEMA_VERSION, "export_id": metadata["export_id"], "files": [
        {"name": name, "size": len(files[name]), "sha256": _sha(files[name])} for name in sorted(files)
    ]}
    files["content_manifest.json"] = _json_bytes(manifest)
    return files


def _write(path, data):
    with path.open("xb") as handle:
        handle.write(data); handle.flush(); os.fsync(handle.fileno())


def export_shadow_report(*, result, output_root, export_id, created_at, operator_purpose, code_version, raw_input_sha256, canonical_input_sha256):
    """Export exactly one immutable three-file evidence namespace outside the repo."""
    metadata = build_export_metadata(result=result, export_id=export_id, created_at=created_at, operator_purpose=operator_purpose, code_version=code_version, raw_input_sha256=raw_input_sha256, canonical_input_sha256=canonical_input_sha256)
    root = _root(output_root); files = _contents(result, metadata); namespace = root / metadata["export_id"]
    temporary = root / ("." + metadata["export_id"] + ".tmp")
    if namespace.exists() or namespace.is_symlink():
        if namespace.is_dir() and not namespace.is_symlink() and verify_shadow_report(namespace) and all(_regular(namespace / name) and (namespace / name).read_bytes() == content for name, content in files.items()): return namespace
        raise ValueError("conflicting export namespace")
    if temporary.exists() or temporary.is_symlink(): raise ValueError("temporary export namespace already exists")
    try:
        temporary.mkdir()
        for name, content in files.items(): _write(temporary / name, content)
        if not _verify(temporary, metadata["export_id"]): raise ValueError("temporary export verification failed")
        os.replace(temporary, namespace)
        if not verify_shadow_report(namespace): raise ValueError("final export verification failed")
        return namespace
    except Exception:
        if temporary.exists() and temporary.is_dir() and not temporary.is_symlink(): shutil.rmtree(temporary)
        raise


def _verify(namespace, expected_export_id=None):
    try:
        path = Path(namespace)
        if not path.is_dir() or path.is_symlink(): return False
        actual = list(path.iterdir())
        if {item.name for item in actual} != _FILES or any(item.is_symlink() or not _regular(item) for item in actual): return False
        manifest_path = path / "content_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
        export_id = _export_id(manifest["export_id"])
        if set(manifest) != {"schema_version", "export_id", "files"} or manifest["schema_version"] != SCHEMA_VERSION or export_id != (expected_export_id or path.name) or not isinstance(manifest["files"], list): return False
        declared = {}
        for item in manifest["files"]:
            if not isinstance(item, dict) or set(item) != {"name", "size", "sha256"}: return False
            name = _safe_name(item["name"]); key = name.casefold()
            if key in declared or not isinstance(item["size"], int) or isinstance(item["size"], bool) or item["size"] < 0: return False
            _digest(item["sha256"], "manifest sha256"); declared[key] = item
        if set(declared) != {name.casefold() for name in _DECLARED}: return False
        for item in declared.values():
            target = path / item["name"]
            if target.stat().st_size != item["size"] or _sha(target.read_bytes()) != item["sha256"]: return False
        result_bytes = (path / "shadow_result.json").read_bytes(); result_data = json.loads(result_bytes, object_pairs_hook=_pairs)
        payload = result_data.get("payload", {})
        metadata = json.loads((path / "export_metadata.json").read_text(encoding="utf-8"), object_pairs_hook=_pairs)
        required = {"schema_version","export_id","shadow_run_id","result_hash","raw_input_sha256","canonical_input_sha256","created_at","operator_purpose","code_version","result_classification","execution_authorized","publication_authorized","runtime_effect","paper_effect","accounting_effect","warnings","limitations","metadata_canonical_sha256"}
        if set(metadata) != required or metadata["schema_version"] != SCHEMA_VERSION or metadata["export_id"] != (expected_export_id or path.name): return False
        if canonical_export_sha256(metadata) != metadata["metadata_canonical_sha256"] or metadata["result_hash"] != _sha(result_bytes): return False
        _digest(metadata["raw_input_sha256"], "raw input hash"); _digest(metadata["canonical_input_sha256"], "canonical input hash")
        if metadata["shadow_run_id"] != payload.get("shadow_run_id") or metadata["result_classification"] != _shadow_runner.RESULT_CLASSIFICATION or payload.get("result_classification") != _shadow_runner.RESULT_CLASSIFICATION: return False
        return all(metadata.get(name) is False and payload.get(name) is False for name in ("execution_authorized","publication_authorized","runtime_effect","paper_effect","accounting_effect"))
    except (OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError): return False


def verify_shadow_report(namespace):
    """Return False unless an exact, non-link immutable shadow export verifies."""
    return _verify(namespace)


__all__ = ["SCHEMA_VERSION", "build_export_metadata", "canonical_export_sha256", "export_shadow_report", "verify_shadow_report"]
