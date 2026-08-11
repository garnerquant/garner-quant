from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from data.point_in_time import FundamentalObservation, UniverseMembership
from research.validated_pipeline import assemble_validated_research, publish_bundle, verify_publication
from research.validated_dataset import ValidatedResearchDataset
from tests.test_validated_research_dataset import bar


OBS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def dataset():
    return ValidatedResearchDataset.from_bars(schema_version=1, dataset_id="d", dataset_version="v1", content_source_hash="h", created_at=OBS, information_cutoff=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), price_basis="adjusted_total_return_research", bar_frequency="1d", instrument_metadata_identity="m1", quality_policy_id="q", quality_policy_version="1", bars=(bar("a"),))


def membership():
    return UniverseMembership(1, "u", "v1", "AAPL", date(2025, 1, 1), None, OBS, True, "included", "m1")


def kwargs(mode="technical_only_historical_v1"):
    return dict(dataset=dataset(), memberships=(membership(),), universe_id="u", universe_version="v1", decision_date=date(2026, 1, 1), information_cutoff=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), evidence_mode=mode, evidence_policy_id="p", evidence_policy_version="1", strategy_id="s", strategy_version="1", parameter_set_id="p1", code_revision="c", created_at=OBS, instrument_metadata_identity="m1", benchmark_instrument="SPY", benchmark_currency_policy="GBP conversion required", execution_model_version="none", cost_model_version="none", run_id="run-1")


def test_end_to_end_technical_bundle_is_reproducible_and_publishable(tmp_path):
    one = assemble_validated_research(**kwargs())
    two = assemble_validated_research(**kwargs())
    assert one.canonical_bytes() == two.canonical_bytes()
    namespace = publish_bundle(one, tmp_path / "isolated_test_root")
    assert verify_publication(namespace)
    assert publish_bundle(two, tmp_path / "isolated_test_root") == namespace
    (namespace / "bundle.json").write_bytes(b"tampered")
    assert not verify_publication(namespace)


def test_point_in_time_mode_uses_only_cutoff_available_observations():
    observation = FundamentalObservation(1, "AAPL", "eps", Decimal("2"), "decimal", "USD", date(2025, 1, 1), date(2025, 12, 31), OBS, OBS, OBS, "fixture", "f1", "run")
    result = assemble_validated_research(**kwargs("point_in_time_fundamental_v1"), fundamental_observations=(observation,), fundamental_requirements=())
    assert result.decision_records[0]["selected_observation_ids"] == []
    assert result.result_classification == "exploratory_unverified"


def test_publication_root_must_be_explicit_and_outside_repository(tmp_path):
    with pytest.raises(ValueError): publish_bundle(assemble_validated_research(**kwargs()), ".")
