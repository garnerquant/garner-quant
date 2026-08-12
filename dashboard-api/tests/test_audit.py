import hashlib, json
from app.evidence import audit

def test_audit_is_deterministic_and_distinguishes_mutability(tmp_path) -> None:
    artifact = tmp_path / "artifact.json"; artifact.write_text("evidence")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps({"artifacts":[{"relative_path":"artifact.json", "sha256":digest, "mutability":"immutable_evidence", "artifact_category":"research"}]}))
    result = audit(manifest_path=manifest, repository_root=tmp_path)
    assert result.records[0].status == "verified"
    assert result.records[0].fields["mutability"] == "immutable_evidence"

def test_audit_rejects_unsafe_paths(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps({"artifacts":[{"relative_path":"../secret", "sha256":"x", "mutability":"immutable_evidence"}]}))
    result = audit(manifest_path=manifest, repository_root=tmp_path)
    assert result.records == []
    assert "redacted" in result.warnings[0]
