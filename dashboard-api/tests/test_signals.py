from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from app.evidence import signals
from app.signals import build_signals

SIGNALS = "date,ticker,signal,weight,status\n2026-01-02,AAA,1,0.2,HOLD / BUY\n2026-01-02,BBB,0,0,AVOID / SELL\n"


def source(tmp_path: Path, text: str = SIGNALS) -> Path:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "signal_report_v2.csv").write_text(text, encoding="utf-8")
    return snapshots


def test_valid_rows_are_sorted_and_timestamped(tmp_path: Path) -> None:
    result = build_signals(datetime(2026, 1, 3, tzinfo=UTC), source(tmp_path))
    assert result.source_classification == "local_snapshot"
    assert [item.instrument for item in result.items] == ["AAA", "BBB"]
    assert result.items[0].as_of_utc == datetime(2026, 1, 2, tzinfo=UTC)
    assert result.freshness.status == "fresh"


def test_duplicate_rows_fail_closed(tmp_path: Path) -> None:
    result = build_signals(datetime(2026, 1, 3, tzinfo=UTC), source(tmp_path, SIGNALS + "2026-01-02,AAA,1,0.2,HOLD / BUY\n"))
    assert result.source_classification == "unavailable"
    assert result.items == []
    assert result.availability.availability == "unavailable"


def test_inconsistent_status_and_dates_fail_closed(tmp_path: Path) -> None:
    inconsistent = SIGNALS.replace("HOLD / BUY", "AVOID / SELL", 1)
    assert build_signals(data_root=source(tmp_path, inconsistent)).availability.availability == "unavailable"
    mixed = SIGNALS.replace("2026-01-02,BBB", "2026-01-03,BBB")
    assert build_signals(data_root=source(tmp_path / "mixed", mixed)).availability.availability == "unavailable"


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    result = build_signals(data_root=tmp_path / "missing")
    assert result.source_classification == "unavailable"
    assert result.freshness.status == "unavailable"


def test_evidence_signals_fail_closed_when_missing(tmp_path: Path) -> None:
    result = signals(datetime(2026, 8, 12, tzinfo=UTC), tmp_path)
    assert result.source_classification == "unavailable"
    assert result.records == []


def test_evidence_signals_select_one_latest_complete_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "signal_report_v2.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "ticker", "status", "signal_code", "target_weight"])
        writer.writeheader()
        writer.writerow({"timestamp": "2026-08-11T00:00:00Z", "ticker": "OLD", "status": "ready", "signal_code": "HOLD", "target_weight": "0"})
        writer.writerow({"timestamp": "2026-08-12T00:00:00Z", "ticker": "AAA", "status": "ready", "signal_code": "BUY", "target_weight": "0.1"})
    result = signals(datetime(2026, 8, 12, 1, tzinfo=UTC), tmp_path)
    assert [item.identity for item in result.records] == ["AAA"]
    assert result.freshness.status == "fresh"
