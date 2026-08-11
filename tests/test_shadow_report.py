"""Offline, isolated tests for immutable shadow report export."""

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from research.shadow_report import build_export_metadata, canonical_export_sha256, export_shadow_report, verify_shadow_report
from research.shadow_runner import run_shadow_comparison
from tests.test_shadow_runner import request


T = datetime(2025, 1, 2, 17, tzinfo=timezone.utc)
HASH = "a" * 64


def result(): return run_shadow_comparison(request())

def export(tmp_path, **changes):
    values = dict(result=result(), output_root=tmp_path, export_id="export-1", created_at=T, operator_purpose="offline evidence review", code_version="code", raw_input_sha256=HASH, canonical_input_sha256="b" * 64)
    values.update(changes)
    return export_shadow_report(**values)


def test_valid_export_verify_exact_files_and_result_safety(tmp_path):
    namespace = export(tmp_path)
    assert verify_shadow_report(namespace)
    assert {path.name for path in namespace.iterdir()} == {"shadow_result.json", "export_metadata.json", "content_manifest.json"}
    metadata = json.loads((namespace / "export_metadata.json").read_text())
    assert metadata["publication_authorized"] is False


def test_metadata_build_is_deterministic_and_does_not_write(tmp_path):
    one = build_export_metadata(result=result(), export_id="id", created_at=T, operator_purpose="purpose", code_version="code", raw_input_sha256=HASH, canonical_input_sha256="b" * 64)
    two = build_export_metadata(result=result(), export_id="id", created_at=T, operator_purpose="purpose", code_version="code", raw_input_sha256=HASH, canonical_input_sha256="b" * 64)
    assert one == two and canonical_export_sha256(one) == one["metadata_canonical_sha256"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("changes", [
    {"output_root": None}, {"output_root": Path(".")}, {"output_root": Path(__file__).parents[1] / "tests"},
    {"export_id": "../bad"}, {"export_id": "bad/path"}, {"created_at": datetime(2025, 1, 2)},
    {"raw_input_sha256": "bad"}, {"canonical_input_sha256": "A" * 64},
])
def test_required_external_root_and_inputs_fail(tmp_path, changes):
    if changes.get("output_root") == Path("."): changes["output_root"] = Path.cwd()
    with pytest.raises((TypeError, ValueError)): export(tmp_path, **changes)


def test_non_utc_timestamp_fails(tmp_path):
    with pytest.raises(ValueError): export(tmp_path, created_at=datetime(2025, 1, 2, tzinfo=timezone(timedelta(hours=1))))


def test_inconsistent_result_and_safety_fail(tmp_path):
    bad = result(); object.__setattr__(bad, "canonical_hash", "0" * 64)
    with pytest.raises(ValueError): export(tmp_path, result=bad)
    unsafe = result(); object.__setattr__(unsafe, "publication_authorized", True)
    with pytest.raises(ValueError): export(tmp_path, result=unsafe)


def test_idempotent_and_conflicting_repeat(tmp_path):
    namespace = export(tmp_path)
    assert export(tmp_path) == namespace
    with pytest.raises(ValueError): export(tmp_path, operator_purpose="different")


@pytest.mark.parametrize("name,mutate", [
    ("unexpected.json", lambda p: p.write_text("{}")), (".hidden", lambda p: p.write_text("x")),
    ("extra", lambda p: p.mkdir()), ("shadow_result.json", lambda p: p.unlink()),
])
def test_unexpected_or_missing_content_fails_verification(tmp_path, name, mutate):
    namespace = export(tmp_path); mutate(namespace / name); assert not verify_shadow_report(namespace)


def test_altered_bytes_metadata_size_hash_and_manifest_fail(tmp_path):
    namespace = export(tmp_path)
    (namespace / "shadow_result.json").write_bytes(b"changed"); assert not verify_shadow_report(namespace)
    root = tmp_path / "two"; root.mkdir(); namespace = export(root)
    metadata = json.loads((namespace / "export_metadata.json").read_text()); metadata["operator_purpose"] = "changed"; (namespace / "export_metadata.json").write_text(json.dumps(metadata)); assert not verify_shadow_report(namespace)
    root = tmp_path / "three"; root.mkdir(); namespace = export(root)
    manifest = json.loads((namespace / "content_manifest.json").read_text()); manifest["files"][0]["size"] += 1; (namespace / "content_manifest.json").write_text(json.dumps(manifest)); assert not verify_shadow_report(namespace)
    (namespace / "content_manifest.json").write_text("{"); assert not verify_shadow_report(namespace)


@pytest.mark.parametrize("name", ["../x", r"C:\\x", r"\\server\\share", "SHADOW_RESULT.JSON"])
def test_duplicate_case_and_unsafe_manifest_paths_fail(tmp_path, name):
    namespace = export(tmp_path); manifest = json.loads((namespace / "content_manifest.json").read_text())
    manifest["files"].append({**manifest["files"][0], "name": name})
    (namespace / "content_manifest.json").write_text(json.dumps(manifest)); assert not verify_shadow_report(namespace)


def test_symlink_is_rejected_when_supported(tmp_path):
    namespace = export(tmp_path)
    try: (namespace / "link").symlink_to(namespace / "shadow_result.json")
    except (OSError, NotImplementedError) as exc: pytest.skip(f"symlink creation unavailable: {exc}")
    assert not verify_shadow_report(namespace)


def test_no_temporary_residue_or_legacy_csv(tmp_path):
    namespace = export(tmp_path)
    assert not list(tmp_path.glob(".*.tmp"))
    assert not any(path.suffix == ".csv" for path in namespace.iterdir())


def test_no_import_write_and_ast_capability_audit(tmp_path):
    before = set(tmp_path.iterdir())
    __import__("research.shadow_report")
    assert set(tmp_path.iterdir()) == before
    tree = ast.parse(Path("research/shadow_report.py").read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module: roots.add(node.module.split(".", 1)[0])
    assert roots.isdisjoint({"runtime", "execution", "risk_engine", "canonical_accounting", "dashboard", "providers", "notifications", "requests", "urllib", "socket", "subprocess", "random", "uuid"})
