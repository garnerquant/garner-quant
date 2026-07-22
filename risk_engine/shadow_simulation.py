from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from risk_engine.audit import RiskDecisionAudit
from risk_engine.authorization import RiskAuthorizationError, verify_risk_authorization
from risk_engine.configuration import load_risk_configuration
from risk_engine.engine import PreTradeRiskEngine
from risk_engine.kill_switch import set_kill_switch
from risk_engine.models import OrderProposal, RiskContext


def run_shadow_simulations(output_dir, *, prices_path=Path("prices_v2.csv")):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = pd.read_csv(prices_path, index_col=0)
    btc_price = Decimal(str(pd.to_numeric(prices["BTC-GBP"], errors="coerce").dropna().iloc[-1]))
    now = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    base = load_risk_configuration()
    config = replace(base, trading_enabled=True, limits_approved=True,
                     configuration_version="shadow-simulation", configuration_hash="shadow-simulation")
    kill_path = output_dir / "kill.json"
    kill_audit = output_dir / "kill-audit.jsonl"
    set_kill_switch(False, actor="shadow-simulation", reason="isolated validation fixture",
                    correlation_id="shadow-simulation", state_path=kill_path, audit_path=kill_audit, now=now)
    audit = RiskDecisionAudit(output_dir / "decisions.jsonl")
    engine = PreTradeRiskEngine(configuration=config, audit=audit, kill_switch_path=kill_path)

    def proposal(name, **changes):
        values = dict(
            proposal_id=name, strategy_id="production-strategy-v1", signal_id="production-bar-fixture",
            symbol="BTC-GBP", market="Crypto", side="BUY", quantity=Decimal("0.01"),
            order_type="MARKET", limit_price=None, stop_price=None, time_in_force="DAY",
            strategy_timestamp=now, source_bar_timestamp=now.replace(hour=0),
            expected_execution_currency="GBP", reason=name, correlation_id="shadow-simulation",
            metadata={"timeframe": "1d"}, created_at=now,
        )
        values.update(changes)
        return OrderProposal.create(**values)

    def context(**changes):
        values = dict(
            now=now, runtime_mode="monitor_only", shadow_mode=True, trading_enabled=False,
            runtime_healthy=True, scheduler_healthy=True, adapter_ready=True, market_session_valid=True,
            source_bar_complete=True, reference_price=btc_price, reference_price_timestamp=now.replace(hour=0),
            fx_rate_to_base=None, fx_timestamp=None, accounting_active=True, accounting_verified=True,
            accounting_generation_id="simulation-only", accounting_base_currency="GBP", accounting_reconciled=True,
            cash_base=Decimal("5000"), portfolio_equity_base=Decimal("10000"), positions_base={},
            position_quantities={}, open_order_notional_base=Decimal("0"), daily_realised_pnl_base=Decimal("0"),
            daily_total_pnl_base=Decimal("0"), equity_high_water_mark_base=Decimal("10000"),
            strategy_exposure_base={}, market_exposure_base={}, currency_exposure_base={}, trace_id="shadow-simulation",
        )
        values.update(changes)
        return RiskContext(**values)

    scenarios = [
        ("valid_buy", proposal("valid-buy"), context()),
        ("valid_sell", proposal("valid-sell", side="SELL"), context(positions_base={"BTC-GBP": btc_price * Decimal("0.02")}, position_quantities={"BTC-GBP": Decimal("0.02")})),
        ("insufficient_cash", proposal("cash", quantity="0.02"), context(cash_base=Decimal("1"))),
        ("position_limit", proposal("position", quantity="0.02"), context(positions_base={"BTC-GBP": Decimal("1900")}, position_quantities={"BTC-GBP": Decimal("0.02")})),
        ("gross_exposure", proposal("gross"), context(positions_base={"ETH-GBP": Decimal("7900")}, position_quantities={"ETH-GBP": Decimal("1")})),
        ("net_exposure", proposal("net"), context(positions_base={"ETH-GBP": Decimal("7900")}, position_quantities={"ETH-GBP": Decimal("1")})),
        ("drawdown", proposal("drawdown"), context(portfolio_equity_base=Decimal("8000"), equity_high_water_mark_base=Decimal("10000"))),
        ("daily_loss", proposal("daily-loss"), context(daily_total_pnl_base=Decimal("-500"))),
        ("stale_data", proposal("stale"), context(now=now + timedelta(days=1))),
        ("missing_fx", proposal("missing-fx", symbol="AAPL", market="NASDAQ", expected_execution_currency="USD"), context(reference_price=Decimal("200"), reference_price_timestamp=now, fx_rate_to_base=None, fx_timestamp=None)),
        ("inactive_accounting", proposal("accounting"), context(accounting_active=False)),
        ("monitor_only", proposal("monitor"), context()),
    ]
    results = []
    for name, item, state in scenarios:
        decision = engine.evaluate(item, state)
        results.append({"scenario": name, "decision": decision.to_dict()})
        if decision.approved or decision.observed_values.get("execution_eligible"):
            raise AssertionError(f"shadow scenario became executable: {name}")

    set_kill_switch(True, actor="shadow-simulation", reason="kill scenario",
                    correlation_id="kill", state_path=kill_path, audit_path=kill_audit, now=now)
    results.append({"scenario": "kill_switch", "decision": engine.evaluate(proposal("kill"), context()).to_dict()})
    set_kill_switch(False, actor="shadow-simulation", reason="duplicate scenario",
                    correlation_id="duplicate", state_path=kill_path, audit_path=kill_audit, now=now)
    duplicate = proposal("duplicate")
    engine.evaluate(duplicate, context())
    results.append({"scenario": "duplicate_proposal", "decision": engine.evaluate(replace(duplicate, quantity=Decimal("0.02")), context()).to_dict()})

    approval_config = config
    approval_engine = PreTradeRiskEngine(configuration=approval_config, audit=RiskDecisionAudit(output_dir / "authorization.jsonl"), kill_switch_path=kill_path)
    approval_proposal = proposal("authorization")
    approval_context = replace(context(), runtime_mode="paper_execution", shadow_mode=False, trading_enabled=True)
    approval = approval_engine.evaluate(approval_proposal, approval_context)
    for name, candidate, check_now in (
        ("expired_approval", approval_proposal, approval.expires_at + timedelta(seconds=1)),
        ("approval_tampering", replace(approval_proposal, quantity=Decimal("0.02")), now),
    ):
        rejected = False
        try:
            verify_risk_authorization(candidate, approval, configuration=approval_config, now=check_now)
        except RiskAuthorizationError:
            rejected = True
        if not rejected:
            raise AssertionError(f"{name} was not rejected")
        results.append({"scenario": name, "decision": approval.to_dict(), "authorization_rejected": True})

    report = {"production_price_source": str(prices_path), "btc_reference_price": str(btc_price),
              "execution_attempts": 0, "scenarios": results}
    (output_dir / "shadow_simulation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
