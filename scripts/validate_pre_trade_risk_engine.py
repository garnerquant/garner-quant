"""Repository validator for the mandatory central pre-trade risk boundary."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.portfolio_manager import commit_trade_state
from risk_engine.audit import RiskDecisionAudit
from risk_engine.configuration import load_risk_configuration
from risk_engine.diagnostics import load_risk_diagnostics
from risk_engine.engine import PreTradeRiskEngine
from risk_engine.kill_switch import load_kill_switch, set_kill_switch
from risk_engine.models import OrderProposal, RiskContext
from risk_engine.reason_codes import REASON_CODES


PROTECTED = (
    "trade_ledger_v1.csv",
    "paper_portfolio_v3.csv",
    "holdings_report.csv",
    "broker_account.csv",
    "paper_30_day_tracker.csv",
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def hashes():
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in PROTECTED
        if (ROOT / name).exists()
    }


def source_checks():
    portfolio = (ROOT / "execution/portfolio_manager.py").read_text(encoding="utf-8")
    main = (ROOT / "main_v2.py").read_text(encoding="utf-8")
    runtime = (ROOT / "runtime/live_runtime.py").read_text(encoding="utf-8")
    legacy = (ROOT / "execution/paper_trader.py").read_text(encoding="utf-8")
    require("central_risk.evaluate(proposal, risk_context)" in portfolio, "portfolio path lacks central evaluation")
    require("verify_risk_authorization(" in portfolio, "commit boundary lacks exact approval verification")
    require("every ledger event requires one central risk authorization" in portfolio, "commit boundary is not fail closed")
    update_call = "update_" + "portfolio("
    require(update_call in main and "bar_timestamps=bar_timestamps" in main, "main path does not pass scheduler evidence")
    require("run_paper_execution" in runtime and "paper_execution_blocked_reason" in runtime, "runtime execution gate missing")
    require("def paper_trade(signals, prices, *, legacy_mode=False" in legacy, "legacy sandbox trader is not default denied")
    require("require_legacy_sandbox(legacy_mode" in legacy, "legacy sandbox guard is missing")
    callers = []
    for path in ROOT.rglob("*.py"):
        if any(part in {".git", ".tmp", "__pycache__", "scripts", "tests"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if update_call in text and path.name != "portfolio_manager.py":
            callers.append(path.relative_to(ROOT).as_posix())
    require(callers == ["main_v2.py"], f"unexpected paper portfolio callers: {callers}")
    require("submit_order" not in portfolio and "place_order" not in portfolio, "live broker submission appeared in paper boundary")


def deterministic_checks(temp_root):
    now = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    config = replace(
        load_risk_configuration(), trading_enabled=True, limits_approved=True,
        configuration_version="validator", configuration_hash="validator-fixture",
    )
    kill = temp_root / "kill.json"
    audit_path = temp_root / "decisions.jsonl"
    set_kill_switch(False, actor="validator", reason="isolated fixture", correlation_id="validator",
                    state_path=kill, audit_path=temp_root / "kill-audit.jsonl", now=now)
    engine = PreTradeRiskEngine(configuration=config, audit=RiskDecisionAudit(audit_path), kill_switch_path=kill)
    proposal = OrderProposal.create(
        proposal_id="validator-proposal", strategy_id="validator-strategy", signal_id="validator-bar",
        symbol="BTC-GBP", market="Crypto", side="BUY", quantity="0.01", order_type="MARKET",
        limit_price=None, stop_price=None, time_in_force="DAY", strategy_timestamp=now,
        source_bar_timestamp=now.replace(hour=0), expected_execution_currency="GBP",
        reason="validator fixture", correlation_id="validator", metadata={"timeframe": "1d"}, created_at=now,
    )
    context = RiskContext(
        now=now, runtime_mode="paper_execution", trading_enabled=True, runtime_healthy=True,
        scheduler_healthy=True, adapter_ready=True, market_session_valid=True, source_bar_complete=True,
        reference_price=Decimal("50000"), reference_price_timestamp=now.replace(hour=0),
        fx_rate_to_base=None, fx_timestamp=None, accounting_active=True, accounting_verified=True,
        accounting_generation_id="fixture", accounting_base_currency="GBP", accounting_reconciled=True,
        cash_base=Decimal("5000"), portfolio_equity_base=Decimal("10000"), positions_base={},
        position_quantities={}, open_order_notional_base=Decimal("0"), daily_realised_pnl_base=Decimal("0"),
        daily_total_pnl_base=Decimal("0"), equity_high_water_mark_base=Decimal("10000"),
        strategy_exposure_base={}, market_exposure_base={}, currency_exposure_base={}, trace_id="validator",
    )
    require(engine.evaluate(proposal, context).approved, "isolated valid proposal did not approve")
    require(engine.evaluate(replace(proposal, proposal_id="stale"), replace(context, now=now.replace(day=23))).primary_reason_code == "MARKET_DATA_STALE", "stale market data did not fail closed")
    require(engine.evaluate(replace(proposal, proposal_id="accounting"), replace(context, accounting_active=False)).primary_reason_code == "ACCOUNTING_INACTIVE", "inactive accounting did not block")
    malformed = replace(proposal, proposal_id="malformed", quantity=Decimal("0"))
    require(engine.evaluate(malformed, context).primary_reason_code == "INVALID_QUANTITY", "malformed proposal did not reject")
    require(audit_path.exists() and audit_path.stat().st_size > 0, "isolated audit was not written")
    try:
        commit_trade_state(
            ledger_events=[{"ticker": "BTC-GBP", "action": "BUY", "shares": "0.01", "price": "50000"}],
            portfolio=None, journal=None, transaction_log=None, snapshots=None, authorizations=[],
        )
    except RuntimeError as exc:
        require("central risk authorization" in str(exc), "execution boundary failed for the wrong reason")
    else:
        raise AssertionError("execution boundary accepted an unauthorised ledger event")
    diagnostics = load_risk_diagnostics(kill_switch_path=kill, audit_path=audit_path)
    require(diagnostics["engine_status"] in {"BLOCKED", "ACTIVE"}, "dashboard diagnostics are not derived from engine state")


def main():
    before = hashes()
    config = load_risk_configuration()
    require(config.trading_enabled is False, "production risk configuration enables trading")
    require(config.limits_approved is False, "production risk limits are marked approved")
    require(len(REASON_CODES) == len(set(REASON_CODES)), "risk reason codes are not unique")
    require(load_kill_switch(ROOT / ".tmp/nonexistent-risk-kill-switch.json").active, "missing kill switch is not fail safe")
    source_checks()
    temp_root = ROOT / ".tmp" / "central_risk_validator"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    try:
        deterministic_checks(temp_root)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    require(before == hashes(), "risk validator modified protected production files")
    print("PASS: central pre-trade risk engine validation")


if __name__ == "__main__":
    main()
