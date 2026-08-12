from datetime import UTC, datetime
from pathlib import Path

from app.portfolio import build_portfolio

PORTFOLIO = "Date,daily_return,equity,peak,drawdown,trading_cost\n2026-01-01,0.01,100,100,0,0\n2026-01-02,0.02,102,102,0,0\n"
COMPLETE_HOLDINGS = "date,ticker,shares,entry_price,current_price,market_value,unrealised_pnl,unrealised_pnl_percent\n2026-01-02,AAA,1,10,12,12,2,0.2\n2026-01-02,BBB,2,5,6,12,2,0.2\n"


def sources(tmp_path: Path, holdings: str = COMPLETE_HOLDINGS, portfolio: str = PORTFOLIO) -> Path:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "portfolio_v2.csv").write_text(portfolio, encoding="utf-8")
    (snapshots / "holdings_report.csv").write_text(holdings, encoding="utf-8")
    return snapshots


def test_complete_snapshot_is_selected_and_reconciled(tmp_path: Path) -> None:
    result = build_portfolio(datetime(2026, 1, 3, tzinfo=UTC), sources(tmp_path))
    assert result.holdings.availability.availability == "available"
    assert [item.instrument for item in result.holdings.items] == ["AAA", "BBB"]
    assert result.portfolio_summary.reconciliation.availability == "unavailable"
    assert result.cash.availability.availability == "unavailable"


def test_exact_timestamp_reconciliation_is_only_claimed_when_values_match(tmp_path: Path) -> None:
    portfolio = "Date,daily_return,equity,peak,drawdown,trading_cost\n2026-01-01,0,20,20,0,0\n2026-01-02,0,24,24,0,0\n"
    result = build_portfolio(datetime(2026, 1, 3, tzinfo=UTC), sources(tmp_path, portfolio=portfolio))
    assert result.portfolio_summary.reconciliation.availability == "available"


def test_mixed_timestamps_are_rejected_as_incomplete(tmp_path: Path) -> None:
    mixed = COMPLETE_HOLDINGS.replace("2026-01-02,BBB", "2026-01-03,BBB")
    result = build_portfolio(datetime(2026, 1, 4, tzinfo=UTC), sources(tmp_path, mixed))
    assert result.holdings.availability.availability == "unavailable"
    assert result.allocation.items == []


def test_duplicate_instrument_is_rejected(tmp_path: Path) -> None:
    duplicate = COMPLETE_HOLDINGS.replace("BBB,2,5,6,12,2,0.2", "AAA,2,5,6,12,2,0.2")
    result = build_portfolio(datetime(2026, 1, 3, tzinfo=UTC), sources(tmp_path, duplicate))
    assert result.holdings.availability.availability == "unavailable"


def test_invalid_decimal_and_missing_column_fail_closed(tmp_path: Path) -> None:
    invalid = COMPLETE_HOLDINGS.replace(",12,2,0.2", ",not-a-decimal,2,0.2", 1)
    result = build_portfolio(datetime(2026, 1, 3, tzinfo=UTC), sources(tmp_path, invalid))
    assert result.holdings.availability.availability == "unavailable"
    result = build_portfolio(datetime(2026, 1, 3, tzinfo=UTC), sources(tmp_path / "missing", "date,ticker\n2026-01-02,AAA\n"))
    assert result.holdings.availability.availability == "unavailable"


def test_latest_complete_snapshot_is_deterministic(tmp_path: Path) -> None:
    twice = COMPLETE_HOLDINGS + "2026-01-03,AAA,1,10,13,13,3,0.3\n2026-01-03,BBB,2,5,7,14,4,0.4\n"
    result = build_portfolio(datetime(2026, 1, 4, tzinfo=UTC), sources(tmp_path, twice))
    assert result.holdings.as_of_utc == datetime(2026, 1, 3, tzinfo=UTC)
    assert result.holdings.items[0].market_value == "13"


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    snapshots = sources(tmp_path)
    (snapshots / "holdings_report.csv").unlink()
    result = build_portfolio(datetime(2026, 1, 3, tzinfo=UTC), snapshots)
    assert result.holdings.availability.availability == "unavailable"
