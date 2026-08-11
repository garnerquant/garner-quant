from datetime import date, datetime, timezone

import pytest

from data.point_in_time import CorporateAction, CorporateActionType, UniverseMembership
from research.universe_selection import select_research_universe
from research.validated_dataset import ValidatedResearchDataset
from tests.test_validated_research_dataset import bar


OBS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def dataset():
    return ValidatedResearchDataset.from_bars(schema_version=1, dataset_id="d", dataset_version="v", content_source_hash="h", created_at=OBS, information_cutoff=datetime(2026, 1, 2, tzinfo=timezone.utc), price_basis="adjusted_total_return_research", bar_frequency="1d", instrument_metadata_identity="m", quality_policy_id="q", quality_policy_version="1", bars=(bar("a"),))


def member(symbol="AAPL", **kwargs):
    values = dict(schema_version=1, universe_id="u", universe_version="v1", instrument_id=symbol, valid_from=date(2025, 1, 1), valid_to=None, available_at=OBS, included=True, reason="included", source_record_id=symbol + "-m")
    values.update(kwargs); return UniverseMembership(**values)


def test_selection_requires_membership_and_is_deterministic():
    one = select_research_universe(dataset=dataset(), universe_id="u", universe_version="v1", decision_date=date(2025, 6, 1), information_cutoff=OBS, memberships=(member(),), metadata_records={"AAPL": object()})
    two = select_research_universe(dataset=dataset(), universe_id="u", universe_version="v1", decision_date=date(2025, 6, 1), information_cutoff=OBS, memberships=(member(),), metadata_records={"AAPL": object()})
    assert one.eligible_instrument_ids == ("AAPL",) and one.canonical_sha256() == two.canonical_sha256()


def test_exclusion_inception_cutoff_and_delisting():
    assert select_research_universe(dataset=dataset(), universe_id="u", universe_version="v1", decision_date=date(2024, 1, 1), information_cutoff=OBS, memberships=(member(),)).eligible_instrument_ids == ()
    late = member(available_at=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert select_research_universe(dataset=dataset(), universe_id="u", universe_version="v1", decision_date=date(2025, 6, 1), information_cutoff=OBS, memberships=(late,)).eligible_instrument_ids == ()
    action = CorporateAction(1, "d1", "AAPL", CorporateActionType.DELISTING, date(2025, 5, 1), OBS, source_name="fixture", source_record_id="d1")
    result = select_research_universe(dataset=dataset(), universe_id="u", universe_version="v1", decision_date=date(2025, 6, 1), information_cutoff=OBS, memberships=(member(),), corporate_actions=(action,))
    assert result.eligible_instrument_ids == () and result.excluded_instrument_reasons == (("AAPL", "explicitly_delisted"),)


def test_ambiguous_and_unknown_metadata_fail_closed_without_config_assets():
    first = member(source_record_id="1", included=True)
    second = member(source_record_id="2", included=False)
    result = select_research_universe(dataset=dataset(), universe_id="u", universe_version="v1", decision_date=date(2025, 6, 1), information_cutoff=OBS, memberships=(first, second))
    assert result.eligible_instrument_ids == () and result.excluded_instrument_reasons == (("AAPL", "ambiguous_membership"),)
    result = select_research_universe(dataset=dataset(), universe_id="u", universe_version="v1", decision_date=date(2025, 6, 1), information_cutoff=OBS, memberships=(member(),), metadata_records={})
    assert result.excluded_instrument_reasons == (("AAPL", "metadata_unavailable"),)
