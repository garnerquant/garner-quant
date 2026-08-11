"""Source-based characterization of historical backtest and paper divergence.

FIND-004/FIND-014 characterization

This module documents current differences between the historical backtest and
paper-trading paths. The differences are not desired parity rules. When a
shared strategy and execution interface is implemented, these tests must be
replaced by identical-input parity tests asserting equal decisions and
explicitly approved adapter differences.
"""

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).parents[1]
BACKTEST = (ROOT / "backtest" / "engine.py").read_text(encoding="utf-8")
COSTS = (ROOT / "backtest" / "costs.py").read_text(encoding="utf-8")
PAPER = (ROOT / "execution" / "portfolio_manager.py").read_text(encoding="utf-8")
RISK = (ROOT / "risk_engine" / "engine.py").read_text(encoding="utf-8")
INTEGRATION = (ROOT / "risk_engine" / "integration.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main_v2.py").read_text(encoding="utf-8")


CONFIRMED_DIVERGENCE = "confirmed divergence"
EQUIVALENT = "equivalent"
UNCLEAR = "unclear/not verified"
NOT_APPLICABLE = "not applicable"
ALLOWED_STATUSES = {CONFIRMED_DIVERGENCE, EQUIVALENT, UNCLEAR, NOT_APPLICABLE}


@dataclass(frozen=True, slots=True)
class DivergenceRow:
    area: str
    backtest_behaviour: str
    paper_behaviour: str
    status: str
    source_evidence: tuple[str, ...]


MATRIX = (
    DivergenceRow("Signal/weight timing", "Uses weights.shift(1) for returns.", "Consumes latest signals and latest weights in update_portfolio().", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Entry-price assumption", "No order fill; returns are based on indexed price changes.", "Uses latest_prices[ticker] as the proposal/reference and entry price.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Exit-price assumption", "Stop/target decisions use prices[ticker].iloc[i].", "Exit decisions use latest_prices[ticker].", EQUIVALENT, ("backtest/engine.py:apply_stops", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Stop-loss trigger", "Sets weight to zero when close-like price <= daily risk-level stop.", "Uses stored position stop_loss and latest price <= stop before risk authorization.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:apply_stops", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Take-profit trigger", "Sets weight to zero when price >= daily risk-level target.", "Uses stored position take_profit and latest price >= target.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:apply_stops", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Same-bar stop/target ambiguity", "Close-only checks use stop first, then target; no intrabar ordering.", "Close/reference-price checks use stop first, then target; no intrabar ordering.", EQUIVALENT, ("backtest/engine.py:apply_stops", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Minimum holding period", "No minimum holding-period check.", "Signal exits require MIN_HOLD_DAYS_FOR_SIGNAL_EXIT.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:signal_exit_status")),
    DivergenceRow("Sell confirmation", "No sell confirmation runs.", "Signal exits require SELL_CONFIRMATION_RUNS confirmations.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:signal_exit_status")),
    DivergenceRow("Fees", "Applies TRANSACTION_FEE to weight turnover.", "No explicit paper fee deduction appears in update_portfolio(); risk context estimates fees as Decimal('0').", CONFIRMED_DIVERGENCE, ("backtest/costs.py:apply_trading_costs", "risk_engine/integration.py:build_production_risk_context")),
    DivergenceRow("Slippage", "Applies SLIPPAGE to weight turnover.", "No paper slippage calculation appears in the inspected active path.", CONFIRMED_DIVERGENCE, ("backtest/costs.py:apply_trading_costs", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Cash handling", "Computes synthetic equity from STARTING_CASH and returns.", "Loads cash/ledger state, caps buys to cash, and mutates cash on trades.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:calculate_cash", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Current-equity handling", "Equity compounds from simulated returns.", "Buy position value uses STARTING_CASH * weight rather than current portfolio equity.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Fractional or share rounding", "Uses weights and does not create share quantities.", "Calculates shares = position_value / price with no visible integer rounding.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Central pre-trade risk authorization", "Does not call PreTradeRiskEngine.", "Builds proposals and calls central_risk.evaluate().", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio", "risk_engine/engine.py:PreTradeRiskEngine.evaluate")),
    DivergenceRow("Kill-switch/risk gating", "No kill-switch or central risk gate in the backtest path.", "PreTradeRiskEngine evaluates trading controls and load_kill_switch().", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "risk_engine/engine.py:PreTradeRiskEngine._evaluate_and_audit")),
    DivergenceRow("Ledger/accounting writes", "Writes trade_log.csv when stops are supplied.", "Commits ledger, portfolio, journal, transaction log and snapshots after authorization.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:commit_trade_state")),
    DivergenceRow("Partial fills", "No order/fill model exists.", "No partial-fill branch is established in the inspected paper path.", UNCLEAR, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Rejected orders", "No order rejection path exists.", "Risk rejection prevents authorization and records a risk reason in decisions.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("Missing/stale data", "Pandas NaN/return behavior is not an explicit freshness policy.", "Missing latest prices are skipped and risk context supplies source-bar completeness, but stale-data policy is not fully established here.", UNCLEAR, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio", "risk_engine/integration.py:build_production_risk_context")),
    DivergenceRow("Drawdown handling", "Applies apply_drawdown_limit() to synthetic portfolio output.", "Central risk evaluates portfolio/drawdown controls before paper authorization.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "risk/risk_manager.py:apply_drawdown_limit", "risk_engine/engine.py:PreTradeRiskEngine")),
    DivergenceRow("Rebalancing", "Calculates a full indexed weight series and applies it to historical returns.", "Processes latest signals/weights against existing holdings and only creates required trade events.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio")),
    DivergenceRow("State/output side effects", "Simulation can write trade_log.csv.", "Paper path writes operational state and may notify after committed trades.", CONFIRMED_DIVERGENCE, ("backtest/engine.py:run_backtest", "execution/portfolio_manager.py:update_portfolio")),
)


def _function_names(source):
    return {node.name for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_divergence_matrix_is_complete_and_explicit():
    required = {
        "Signal/weight timing", "Entry-price assumption", "Exit-price assumption",
        "Stop-loss trigger", "Take-profit trigger", "Same-bar stop/target ambiguity",
        "Minimum holding period", "Sell confirmation", "Fees", "Slippage", "Cash handling",
        "Current-equity handling", "Fractional or share rounding", "Central pre-trade risk authorization",
        "Kill-switch/risk gating", "Ledger/accounting writes", "Partial fills", "Rejected orders",
        "Missing/stale data", "Drawdown handling", "Rebalancing", "State/output side effects",
    }
    assert len(MATRIX) == len(required)
    assert {row.area for row in MATRIX} == required
    assert all(row.status in ALLOWED_STATUSES for row in MATRIX)
    assert all(row.source_evidence and all(item for item in row.source_evidence) for row in MATRIX)
    assert any(row.status == CONFIRMED_DIVERGENCE for row in MATRIX)
    assert any(row.status == UNCLEAR for row in MATRIX)


def test_backtest_timing_and_cost_path_are_characterized():
    assert "weights.shift(1)" in BACKTEST
    assert "prices.pct_change()" in BACKTEST
    assert "apply_trading_costs(portfolio, weights)" in BACKTEST
    assert "TRANSACTION_FEE + SLIPPAGE" in COSTS
    assert "apply_trading_costs" not in PAPER
    assert "weights.shift(1)" not in PAPER


def test_exit_and_confirmation_paths_are_characterized():
    assert "price <= stop" in BACKTEST
    assert "price >= target" in BACKTEST
    assert "current_price <= stop_loss" in PAPER
    assert "current_price >= take_profit" in PAPER
    assert "MIN_HOLD_DAYS_FOR_SIGNAL_EXIT" in PAPER
    assert "SELL_CONFIRMATION_RUNS" in PAPER
    assert "trade_log.to_csv" in BACKTEST


def test_risk_accounting_and_orchestration_paths_are_characterized():
    assert "PreTradeRiskEngine" not in BACKTEST
    assert "central_risk.evaluate(proposal, risk_context)" in PAPER
    assert "load_kill_switch" in RISK
    assert "commit_trade_state(" in PAPER
    assert "build_trade_event(" in PAPER
    assert "run_backtest(asset_prices, weights, risk_levels)" in MAIN
    assert "update_portfolio(" in MAIN
    assert "strategy.contract" not in "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in ("backtest/engine.py", "execution/portfolio_manager.py", "main_v2.py")
    )


def test_no_shared_parity_contract_or_direct_parity_test_is_present():
    production = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in ("backtest/engine.py", "backtest/costs.py", "execution/portfolio_manager.py", "main_v2.py")
    )
    assert "strategy.contract" not in production
    parity_files = []
    for path in (ROOT / "tests").glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        if "run_backtest" in text and "update_portfolio" in text:
            parity_files.append(path.name)
    assert parity_files == []
