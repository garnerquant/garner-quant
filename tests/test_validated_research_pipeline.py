from datetime import date, datetime, timezone
from decimal import Decimal
import json

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


def _published(tmp_path):
    return publish_bundle(assemble_validated_research(**kwargs()), tmp_path / "isolated_test_root")


@pytest.mark.parametrize("name", ["unexpected.json", ".hidden", ".research-leftover"])
def test_publication_rejects_unexpected_files(tmp_path, name):
    namespace = _published(tmp_path)
    (namespace / name).write_text("x", encoding="utf-8")
    assert not verify_publication(namespace)


def test_publication_rejects_unexpected_directory(tmp_path):
    namespace = _published(tmp_path)
    (namespace / "extra").mkdir()
    assert not verify_publication(namespace)


def test_publication_rejects_missing_or_modified_content(tmp_path):
    namespace = _published(tmp_path)
    (namespace / "bundle.json").unlink()
    assert not verify_publication(namespace)
    namespace = _published(tmp_path / "second")
    (namespace / "bundle.json").write_bytes(b"changed")
    assert not verify_publication(namespace)


def test_publication_rejects_invalid_manifest_metadata(tmp_path):
    namespace = _published(tmp_path)
    manifest_path = namespace / "content_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["size"] = -1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not verify_publication(namespace)


@pytest.mark.parametrize("name", ["../outside.json", r"..\outside.json", "C:/outside.json", r"C:\outside.json", r"\\server\share\outside.json", "evidence/../../outside.json"])
def test_publication_rejects_unsafe_manifest_paths(tmp_path, name):
    namespace = _published(tmp_path)
    manifest_path = namespace / "content_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["name"] = name
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not verify_publication(namespace)


def test_publication_rejects_duplicate_and_case_collision_entries(tmp_path):
    namespace = _published(tmp_path)
    manifest_path = namespace / "content_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item = dict(manifest["files"][0])
    manifest["files"].append(item)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not verify_publication(namespace)
    namespace = _published(tmp_path / "case")
    manifest_path = namespace / "content_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append({**manifest["files"][0], "name": "BUNDLE.JSON"})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not verify_publication(namespace)


def test_publication_rejects_symlink_when_supported(tmp_path):
    namespace = _published(tmp_path)
    try:
        (namespace / "link").symlink_to(namespace / "bundle.json")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    assert not verify_publication(namespace)
