from datetime import UTC, datetime
from pathlib import Path

from app.overview import build_overview


PORTFOLIO = "Date,daily_return,equity,peak,drawdown,trading_cost\n2026-01-01,0.01,100,100,0,0\n2026-01-02,0.02,102,102,0,0\n"
HOLDINGS = "date,ticker,shares,entry_price,current_price,market_value,unrealised_pnl,unrealised_pnl_percent\n2026-01-02 12:00:00,AAA,1,10,12,12,2,0.2\n2026-01-02 12:00:00,BBB,2,5,6,12,2,0.2\n"
SIGNALS = "date,ticker,signal,weight,status\n2026-01-02,BBB,1,0.2,HOLD / BUY\n2026-01-02,AAA,0,0,AVOID / SELL\n"
CONFIG = '{"mode":"monitor_only","paper_execution_enabled":false}'
RISK_CONFIG = '{"trading_enabled":false,"limits_approved":false}'


def write_sources(tmp_path: Path, portfolio: str = PORTFOLIO, holdings: str = HOLDINGS, signals: str = SIGNALS, risk_config: str = RISK_CONFIG) -> tuple[Path, Path]:
    snapshots = tmp_path / "snapshots"
    config = tmp_path / "config"
    snapshots.mkdir(parents=True)
    config.mkdir(parents=True)
    (snapshots / "portfolio_v2.csv").write_text(portfolio, encoding="utf-8")
    (snapshots / "holdings_report.csv").write_text(holdings, encoding="utf-8")
    (snapshots / "signal_report_v2.csv").write_text(signals, encoding="utf-8")
    (config / "live_runtime_config.json").write_text(CONFIG, encoding="utf-8")
    (config / "risk_config.json").write_text(risk_config, encoding="utf-8")
    return snapshots, config


def test_valid_response_is_deterministic(tmp_path: Path) -> None:
    snapshots, config = write_sources(tmp_path)
    result = build_overview(datetime(2026, 1, 3, tzinfo=UTC), snapshots, config)
    assert result.schema_version == "overview.v1"
    assert result.portfolio_summary.portfolio_value == "102"
    assert result.portfolio_summary.daily_change_percent == "2.00"
    assert result.holdings_summary.holdings[0]["instrument"] == "AAA"
    assert [item.instrument for item in result.recent_signals.items] == ["AAA", "BBB"]
    assert result.generated_at_utc == datetime(2026, 1, 3, tzinfo=UTC)
    assert result.source_as_of_utc == datetime(2026, 1, 2, tzinfo=UTC)
    assert result.snapshot_freshness.snapshot_age_seconds == 86400
    assert result.snapshot_freshness.status == "fresh"
    assert result.portfolio_summary.latest_recorded_change_as_of_utc == datetime(2026, 1, 2, tzinfo=UTC)
    assert result.risk_safety_summary.mode.value == "Monitor only"
    assert result.risk_safety_summary.paper_execution_enabled.value == "Disabled"
    assert result.risk_safety_summary.trading_enabled.value == "Disabled"
    assert result.risk_safety_summary.limits_approved.value == "No"


def test_stale_snapshot_age_is_deterministic(tmp_path: Path) -> None:
    snapshots, config = write_sources(tmp_path)
    result = build_overview(datetime(2026, 1, 4, 0, 0, 1, tzinfo=UTC), snapshots, config)
    assert result.snapshot_freshness.snapshot_age_seconds == 172801
    assert result.snapshot_freshness.freshness_threshold_seconds == 86400
    assert result.snapshot_freshness.status == "stale"


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    snapshots, config = write_sources(tmp_path)
    (snapshots / "portfolio_v2.csv").unlink()
    result = build_overview(data_root=snapshots, config_root=config)
    assert result.portfolio_summary.availability["portfolio_value"].availability == "unavailable"


def test_malformed_and_unsupported_csv_fail_closed(tmp_path: Path) -> None:
    snapshots, config = write_sources(tmp_path, portfolio="Date,equity\n2026-01-01,100\n")
    result = build_overview(data_root=snapshots, config_root=config)
    assert result.performance_series.availability.availability == "unavailable"


def test_duplicate_instrument_fails_closed(tmp_path: Path) -> None:
    duplicate = HOLDINGS.replace("BBB,2,5,6,12,2,0.2", "AAA,2,5,6,12,2,0.2")
    snapshots, config = write_sources(tmp_path, holdings=duplicate)
    result = build_overview(data_root=snapshots, config_root=config)
    assert result.holdings_summary.availability.availability == "unavailable"
    assert result.holdings_summary.holdings == []


def test_invalid_decimal_fails_closed(tmp_path: Path) -> None:
    snapshots, config = write_sources(tmp_path, signals=SIGNALS.replace("0.2", "invalid"))
    result = build_overview(data_root=snapshots, config_root=config)
    assert result.recent_signals.availability.availability == "unavailable"


def test_inconsistent_holdings_timestamps_fail_closed(tmp_path: Path) -> None:
    inconsistent = HOLDINGS.replace("2026-01-02 12:00:00,BBB", "2026-01-02 12:01:00,BBB")
    snapshots, config = write_sources(tmp_path, holdings=inconsistent)
    result = build_overview(data_root=snapshots, config_root=config)
    assert result.holdings_summary.availability.availability == "unavailable"
    assert result.allocation.items == []


def test_missing_or_malformed_risk_configuration_fails_closed(tmp_path: Path) -> None:
    snapshots, config = write_sources(tmp_path)
    (config / "risk_config.json").unlink()
    missing = build_overview(data_root=snapshots, config_root=config)
    assert missing.risk_safety_summary.trading_enabled.availability.availability == "unavailable"
    snapshots, config = write_sources(tmp_path / "malformed", risk_config='{"trading_enabled":"false"}')
    malformed = build_overview(data_root=snapshots, config_root=config)
    assert malformed.risk_safety_summary.limits_approved.availability.availability == "unavailable"
    snapshots, config = write_sources(tmp_path / "wrong-shape", risk_config="[]")
    wrong_shape = build_overview(data_root=snapshots, config_root=config)
    assert wrong_shape.risk_safety_summary.trading_enabled.availability.availability == "unavailable"
