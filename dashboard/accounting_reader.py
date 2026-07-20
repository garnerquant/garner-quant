from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from canonical_accounting.generation import AccountingGeneration, GenerationError, load_active_generation


@dataclass(frozen=True)
class DashboardAccountingBundle:
    generation_id: str
    manifest: dict
    broker: pd.DataFrame
    holdings: pd.DataFrame
    tracker: pd.DataFrame
    ledger: pd.DataFrame


def load_dashboard_accounting(state_root=Path("data/accounting_generations")) -> DashboardAccountingBundle:
    generation = load_active_generation(state_root)
    broker = generation.broker.rename(columns={
        "base_cash": "cash", "base_positions_value": "positions_value",
        "base_total_equity": "portfolio_value", "base_realised_pnl": "realised_pnl",
        "base_unrealised_pnl": "unrealised_pnl",
    }).copy(deep=True)
    broker["buying_power"] = broker["cash"]
    holdings = generation.holdings.rename(columns={
        "symbol": "ticker", "native_price": "current_price",
        "base_market_value": "market_value", "base_unrealised_pnl": "unrealised_pnl",
    }).copy(deep=True)
    tracker = generation.tracker.rename(columns={
        "timestamp": "date", "base_cash": "cash",
        "base_total_equity": "portfolio_value", "base_realised_pnl": "realised_pnl",
        "base_unrealised_pnl": "unrealised_pnl",
    }).copy(deep=True)
    return DashboardAccountingBundle(
        generation.generation_id, dict(generation.manifest), broker,
        holdings, tracker, generation.ledger.copy(deep=True),
    )
