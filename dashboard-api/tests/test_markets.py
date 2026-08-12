from datetime import UTC, datetime
from app.evidence import markets

def test_markets_fail_closed_without_validated_snapshot() -> None:
    result = markets(datetime(2026, 8, 12, tzinfo=UTC))
    assert result.schema_version == "markets.v1"
    assert result.source_classification == "unavailable"
    assert result.records == []
    assert "Currency" in result.provenance[1]
