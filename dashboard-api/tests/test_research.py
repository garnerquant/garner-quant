import json
from datetime import UTC, datetime
from app.evidence import research

def test_research_labels_incomplete_manifest_unverified(tmp_path) -> None:
    folder = tmp_path / "run"; folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({"report_id":"run-1", "created_at":"2026-08-12T00:00:00Z", "schema_version":"v1", "content_hash":"abc", "evidence_snapshot_id":"dataset-1"}))
    result = research(datetime(2026, 8, 12, 1, tzinfo=UTC), tmp_path)
    assert result.records[0].status == "unverified"
    assert result.records[0].fields["code_version"] is None
    assert result.source_classification == "partial"
