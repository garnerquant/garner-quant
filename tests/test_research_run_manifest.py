from datetime import datetime, timezone
from research.run_manifest import ResearchRunManifest, manifest_bytes, manifest_sha256


def make(**overrides):
    values = dict(schema_version=1, run_id="run-1", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), strategy_id="s", strategy_version="v1", parameter_set_id="p", universe_id="u", universe_version="u1", information_cutoff=datetime(2026, 1, 2, tzinfo=timezone.utc), datasets=(("prices", "v1", "abc"), ("fundamentals", "v1", "def")), code_revision="commit", instrument_metadata_version="m1", price_basis="adjusted_total_return_research", benchmark_instrument="SPY", benchmark_currency_policy="GBP_conversion_required", execution_model_version="none", cost_model_version="none")
    values.update(overrides); return ResearchRunManifest(**values)


def test_manifest_is_deterministic_and_caller_supplied():
    one, two = make(), make()
    assert manifest_bytes(one) == manifest_bytes(two)
    assert manifest_sha256(one) == manifest_sha256(two)
    assert len(manifest_sha256(one)) == 64
    assert "exploratory_unverified" in manifest_bytes(one).decode()


def test_manifest_rejects_missing_or_unsafe_provenance():
    import pytest
    with pytest.raises(ValueError): make(code_revision="")
    with pytest.raises(ValueError): make(result_classification="validated")
