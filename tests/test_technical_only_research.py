from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from data.point_in_time import canonical_point_in_time_sha256
from research.technical_only import MODE, run_technical_only
from strategy.contract import BarStatus, DataQualityStatus, NormalizedMarketBar
from strategy.serialization import canonical_sha256


def bar(record="r1", status=BarStatus.COMPLETED, quality=DataQualityStatus.VALID, end_hour=10):
    return NormalizedMarketBar("AAPL", datetime(2026, 1, 1, 9, tzinfo=timezone.utc), datetime(2026, 1, 1, end_hour, tzinfo=timezone.utc), date(2026, 1, 1), Decimal("100"), Decimal("103"), Decimal("99"), Decimal("102"), Decimal("1000"), "USD", "USD", status, quality, "prices-v1", record)


def run(bars=(bar(),)):
    return run_technical_only(mode=MODE, bars=bars, information_cutoff_utc=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), strategy_id="technical-only", strategy_version="v1", parameter_version="p1", universe_version="u1", code_revision="c1")


def test_explicit_mode_is_deterministic_and_unverified():
    one, two = run(), run()
    assert one == two
    assert one.classification == "exploratory_unverified"
    assert one.decisions[0].decision_action.value == "buy"
    assert canonical_sha256(one.decisions[0]) == canonical_sha256(two.decisions[0])


def test_unknown_mode_and_ineligible_bars_fail_closed():
    with pytest.raises(ValueError): run_technical_only(mode="", bars=(bar(),), information_cutoff_utc=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), strategy_id="s", strategy_version="v", parameter_version="p", universe_version="u", code_revision="c")
    rejected = run((bar(status=BarStatus.INCOMPLETE, quality=DataQualityStatus.INVALID),))
    assert rejected.decisions[0].decision_status.value == "rejected"
    assert rejected.decisions[0].reason_codes == ("bar_not_eligible_for_historical_decision",)


def test_future_bar_is_rejected_and_no_fundamental_or_provider_path_exists():
    rejected = run((bar(end_hour=13),))
    assert rejected.decisions[0].decision_status.value == "rejected"
    from pathlib import Path
    source = (Path(__file__).parents[1] / "research" / "technical_only.py").read_text(encoding="utf-8")
    assert "fundamental_pass" not in source
    assert "get_fundamental_score" not in source
    assert "yfinance" not in source


def test_active_paths_do_not_import_technical_only_mode():
    from pathlib import Path
    root = Path(__file__).parents[1]
    for relative in ("main_v2.py", "strategy/signals.py", "execution/portfolio_manager.py", "runtime/live_runtime.py"):
        assert "research.technical_only" not in (root / relative).read_text(encoding="utf-8")
