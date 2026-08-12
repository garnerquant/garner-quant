from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import uuid

import pandas as pd

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *args, **kwargs: object()))

import main_v2
from execution import mark_to_market as mtm


def test_shadow_mode_writes_read_only_dashboard_snapshots(monkeypatch) -> None:
    index = pd.Index([pd.Timestamp("2026-08-12")], name="Date")
    close = pd.DataFrame({"IUSA.L": [100.0]}, index=index)
    high = pd.DataFrame({"IUSA.L": [101.0]}, index=index)
    low = pd.DataFrame({"IUSA.L": [99.0]}, index=index)
    volume = pd.DataFrame({"IUSA.L": [1000.0]}, index=index)
    signals = pd.DataFrame({"IUSA.L": [1]}, index=index)
    weights = pd.DataFrame({"IUSA.L": [0.2]}, index=index)
    risk_levels = pd.DataFrame({"stop_loss": [95.0], "take_profit": [110.0]}, index=index)
    trades = pd.DataFrame()
    trades.attrs["risk_decisions"] = []
    written: dict[str, pd.DataFrame] = {}

    monkeypatch.setattr(main_v2, "download_market_data", lambda tickers: object())
    monkeypatch.setattr(
        main_v2,
        "get_price_field",
        lambda data, field: {
            "Close": close,
            "High": high,
            "Low": low,
            "Volume": volume,
        }[field],
    )
    monkeypatch.setattr(main_v2, "build_signals", lambda asset_prices, asset_volumes: signals)
    monkeypatch.setattr(main_v2, "build_risk_levels", lambda asset_prices, asset_highs, asset_lows: risk_levels)
    monkeypatch.setattr(main_v2, "build_weights", lambda signal_frame, price_frame, risk_frame: weights)
    monkeypatch.setattr(
        main_v2,
        "run_backtest",
        lambda asset_prices, weight_frame, risk_frame: pd.DataFrame({"equity": [10000.0]}, index=index),
    )
    monkeypatch.setattr(
        main_v2,
        "update_portfolio",
        lambda *args, **kwargs: (pd.DataFrame(), pd.DataFrame(), trades),
    )
    monkeypatch.setattr(
        main_v2,
        "atomic_write_csv_frames",
        lambda frames, **kwargs: written.update({str(path): frame.copy() for path, frame in frames.items()}),
    )

    result = main_v2._run_main_unlocked(
        show_charts=False,
        send_telegram=False,
        sync_remote=False,
        eligible_symbols=["IUSA.L"],
        bar_identities={"IUSA.L": "bar-identity"},
        bar_timestamps={"IUSA.L": "2026-08-12T15:30:00+00:00"},
        shadow_mode=True,
    )

    assert result["status"] == "shadow_complete"
    assert {
        "prices_v2.csv",
        "signals_v2.csv",
        "weights_v2.csv",
        "risk_levels_v2.csv",
        "signal_report_v2.csv",
    }.issubset(written)
    assert "portfolio_v2.csv" not in written
    assert "holdings_report.csv" not in written
    signal_report = written["signal_report_v2.csv"]
    assert signal_report.to_dict("records") == [
        {
            "date": pd.Timestamp("2026-08-12 00:00:00"),
            "ticker": "IUSA.L",
            "signal": 1,
            "weight": 0.2,
            "status": "HOLD / BUY",
        }
    ]


def test_mark_to_market_refresh_normalizes_snapshot_timestamps_and_advances_portfolio_date(
    monkeypatch,
) -> None:
    base = Path(tempfile.gettempdir()) / f"dashboard-evidence-refresh-{uuid.uuid4().hex}"
    base.mkdir()
    (base / "paper_portfolio_v3.csv").write_text(
        "\n".join(
            [
                "ticker,entry_date,entry_price,shares,position_value,stop_loss,take_profit,signal_exit_count,last_signal_exit_check,current_price,market_value,unrealised_pnl,unrealised_pnl_pct,valuation_updated_at",
                "AAPL,2026-08-01,10,1,10,0,0,0,,12,12,2,0.2,2026-08-12 16:52:23",
                "MSFT,2026-08-01,20,2,40,0,0,0,,24,48,8,0.2,2026-08-12 17:33:41",
            ]
        ),
        encoding="utf-8",
    )
    (base / "holdings_report.csv").write_text(
        "\n".join(
            [
                "date,ticker,shares,entry_price,current_price,market_value,unrealised_pnl,unrealised_pnl_percent",
                "2026-08-12 16:52:23,AAPL,1,10,12,12,2,0.2",
                "2026-08-12 17:33:41,MSFT,2,20,24,48,8,0.2",
            ]
        ),
        encoding="utf-8",
    )
    (base / "portfolio_v2.csv").write_text(
        "\n".join(
            [
                "Date,daily_return,equity,peak,drawdown,trading_cost",
                "2026-07-15,0.0,100.0,100.0,0.0,0.0",
                "2026-07-16,0.0,102.0,102.0,0.0,0.0",
            ]
        ),
        encoding="utf-8",
    )
    (base / "paper_30_day_tracker.csv").write_text(
        "\n".join(
            [
                "date,portfolio_value,cash,realised_pnl,unrealised_pnl,benchmark_return,alpha",
                "2026-07-16 00:00:00,102,50,0,10,0,0",
            ]
        ),
        encoding="utf-8",
    )
    (base / "trade_journal_v3.csv").write_text(
        "date,time,action,ticker,price,shares,value,pnl,pnl_percent,reason\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mtm,
        "authoritative_ledger_accounting",
        lambda base_dir=".": {
            "open_lots": pd.DataFrame(
                [
                    {"ticker": "AAPL", "shares": 1},
                    {"ticker": "MSFT", "shares": 2},
                ]
            )
        },
    )
    monkeypatch.setattr(
        mtm,
        "broker_values_from_ledger_and_holdings",
        lambda *, holdings, portfolio, base_dir=".": {
            "cash": 1000.0,
            "buying_power": 1000.0,
            "positions_value": float(holdings["market_value"].sum()),
            "portfolio_value": 1056.0,
            "realised_pnl": 0.0,
            "unrealised_pnl": float(holdings["unrealised_pnl"].sum()),
        },
    )
    monkeypatch.setattr(
        mtm,
        "atomic_write_csv_frames",
        lambda frames_by_path, **kwargs: [
            (
                Path(path).parent.mkdir(parents=True, exist_ok=True),
                frame.to_csv(path, index=False),
            )
            for path, frame in frames_by_path.items()
        ],
    )

    result = mtm.mark_to_market_refresh(
        monitor_result={
            "latest_prices": {
                "AAPL": {"price": 12.0, "timestamp": "2026-08-12T17:33:41Z"},
                "MSFT": {"price": 22.0, "timestamp": "2026-08-12T17:33:41Z"},
            }
        },
        sync_remote=False,
        base_dir=base,
    )

    assert result["status"] == "success"
    refreshed_holdings = pd.read_csv(base / "holdings_report.csv")
    assert refreshed_holdings["date"].nunique() == 1
    assert refreshed_holdings["date"].iloc[0] == refreshed_holdings["date"].iloc[-1]

    refreshed_portfolio = pd.read_csv(base / "portfolio_v2.csv")
    assert refreshed_portfolio["Date"].iloc[-1] == refreshed_holdings["date"].iloc[0].split(" ", 1)[0]
    assert float(refreshed_portfolio["equity"].iloc[-1]) == 1056.0
