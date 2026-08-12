from app.evidence import shadow_runs

def test_shadow_endpoint_has_no_runtime_or_export_capability() -> None:
    result = shadow_runs()
    assert result.records == []
    assert result.source_classification == "unavailable"
    assert "cannot accept input" in result.provenance[1]
