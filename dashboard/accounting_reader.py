from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from canonical_accounting.generation import AccountingGeneration, GenerationError, load_active_generation
from canonical_accounting.snapshot import CanonicalPortfolioSnapshot
from canonical_accounting.successor import load_transactional_generation


@dataclass(frozen=True)
class DashboardAccountingBundle:
    generation_id: str
    manifest: dict
    broker: pd.DataFrame
    holdings: pd.DataFrame
    tracker: pd.DataFrame
    ledger: pd.DataFrame
    snapshot: CanonicalPortfolioSnapshot | None = None


@dataclass(frozen=True)
class DashboardAccountingStatus:
    state: str
    bundle: DashboardAccountingBundle | None
    reason: str | None


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
    try:
        _, snapshot, _ = load_transactional_generation(generation.path, expected_id=generation.generation_id)
    except Exception:
        snapshot = None
    return DashboardAccountingBundle(
        generation.generation_id, dict(generation.manifest), broker,
        holdings, tracker, generation.ledger.copy(deep=True), snapshot,
    )


def load_dashboard_accounting_status(
    state_root=Path("data/accounting_generations"),
) -> DashboardAccountingStatus:
    state_root = Path(state_root)
    pointer = state_root / "accounting_generation.json"
    try:
        pointer_exists = pointer.exists()
    except OSError:
        pointer_exists = True
    try:
        bundle = load_dashboard_accounting(state_root)
    except GenerationError as exc:
        reason = str(exc)
        state = "pending" if not pointer_exists else "error"
        return DashboardAccountingStatus(state=state, bundle=None, reason=reason)
    return DashboardAccountingStatus(state="active", bundle=bundle, reason=None)
