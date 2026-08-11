from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from data.point_in_time import FundamentalObservation
from research.fundamental_snapshots import FundamentalSnapshotStore, SnapshotStoreError


OBS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def item(record="r1", value=Decimal("1.0"), available=OBS, revision=None):
    return FundamentalObservation(1, "AAPL", "eps", value, "decimal", "USD", date(2025, 1, 1), date(2025, 12, 31), OBS, OBS, available, "fixture", record, "run", "valid", revision)


def test_append_query_cutoff_duplicate_and_revision(tmp_path):
    store = FundamentalSnapshotStore(tmp_path / "isolated_test_root")
    store.append(item())
    store.append(item())
    assert len(store.query("AAPL", "eps", OBS)) == 1
    assert store.query("AAPL", "eps", datetime(2025, 1, 1, tzinfo=timezone.utc)) == ()
    store.append(item("r2", Decimal("2"), OBS, "rev2"))
    assert [x.value for x in store.query("AAPL", "eps", OBS)] == [Decimal("1.0"), Decimal("2")]
    with pytest.raises(SnapshotStoreError): store.append(item("r1", Decimal("9")))


def test_corruption_fails_closed_and_hash_is_deterministic(tmp_path):
    store = FundamentalSnapshotStore(tmp_path / "isolated_test_root")
    store.append(item())
    first = store.content_hash()
    store.path.write_text(store.path.read_text(encoding="utf-8").replace("r1", "broken"), encoding="utf-8")
    with pytest.raises(SnapshotStoreError): store.query("AAPL", "eps", OBS)
    assert first != store.content_hash()
