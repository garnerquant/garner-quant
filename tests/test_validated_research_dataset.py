from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from research.validated_dataset import ValidatedResearchDataset
from strategy.contract import BarStatus, DataQualityStatus, NormalizedMarketBar


def bar(record="r1", end=10, status=BarStatus.COMPLETED, quality=DataQualityStatus.VALID):
    return NormalizedMarketBar("AAPL", datetime(2026, 1, 1, 9, tzinfo=timezone.utc), datetime(2026, 1, 1, end, tzinfo=timezone.utc), date(2026, 1, 1), Decimal("100"), Decimal("103"), Decimal("99"), Decimal("102"), Decimal("10"), "USD", "USD", status, quality, "prices", record)


def make(bars=(bar(),), **kwargs):
    values = dict(schema_version=1, dataset_id="d", dataset_version="v1", content_source_hash="sha", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), information_cutoff=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), price_basis="adjusted_total_return_research", bar_frequency="1h", instrument_metadata_identity="meta-v1", quality_policy_id="q", quality_policy_version="1", bars=bars)
    values.update(kwargs); return ValidatedResearchDataset.from_bars(**values)


def test_valid_adjusted_dataset_is_order_invariant_and_hashed():
    one = make(bars=(bar("r1"), bar("r2", end=11)))
    two = make(bars=(bar("r2", end=11), bar("r1")))
    assert one.bars == two.bars
    assert one.canonical_bytes() == two.canonical_bytes()
    assert len(one.canonical_sha256()) == 64


def test_raw_dataset_requires_explicit_corporate_actions():
    with pytest.raises(ValueError): make(price_basis="raw_execution_with_actions")
    assert make(price_basis="raw_execution_with_actions", corporate_action_dataset_identity="actions-v1").price_basis == "raw_execution_with_actions"


@pytest.mark.parametrize("status,quality", [(BarStatus.INCOMPLETE, DataQualityStatus.INVALID), (BarStatus.COMPLETED, DataQualityStatus.STALE)])
def test_incomplete_and_stale_bars_fail_closed(status, quality):
    with pytest.raises(ValueError): make(bars=(bar(status=status, quality=quality),))


def test_future_and_conflicting_duplicates_fail_but_exact_duplicates_are_idempotent():
    with pytest.raises(ValueError): make(bars=(bar(end=13),))
    assert len(make(bars=(bar(), bar())).bars) == 1
    with pytest.raises(ValueError): make(bars=(bar(), bar(record="r1", end=11)))


def test_missing_provenance_and_unknown_basis_rejected():
    with pytest.raises(ValueError): make(dataset_id="")
    with pytest.raises(ValueError): make(price_basis="unknown")
    assert "bars" in make().payload()["payload"]
