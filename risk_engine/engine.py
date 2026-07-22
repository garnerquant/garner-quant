from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from canonical_accounting.instruments import get_instrument_metadata
from risk_engine.audit import RiskAuditError, RiskDecisionAudit
from risk_engine.configuration import RiskConfiguration, load_risk_configuration
from risk_engine.kill_switch import load_kill_switch
from risk_engine.models import (
    DecisionStatus,
    OrderProposal,
    RiskContext,
    RiskDecision,
    RiskFinding,
    decimal_value,
)


SOFTWARE_VERSION = "central-pre-trade-risk-v1"
PROPOSAL_REASON_CODES = frozenset({
    "INVALID_PROPOSAL", "UNKNOWN_INSTRUMENT", "UNSUPPORTED_MARKET",
    "INVALID_QUANTITY", "UNSUPPORTED_ORDER_TYPE", "DUPLICATE_PROPOSAL",
})
BLOCK_REASON_CODES = frozenset({
    "MARKET_DATA_MISSING", "MARKET_DATA_STALE", "FX_RATE_MISSING", "FX_RATE_STALE",
    "ACCOUNTING_INACTIVE", "ACCOUNTING_UNVERIFIED", "PORTFOLIO_STATE_UNAVAILABLE",
    "KILL_SWITCH_ACTIVE", "TRADING_DISABLED", "RUNTIME_UNHEALTHY",
    "SCHEDULER_UNHEALTHY", "BROKER_UNAVAILABLE", "INTERNAL_RISK_ERROR",
    "AUDIT_WRITE_FAILED", "RISK_LIMITS_UNAPPROVED",
})


class PreTradeRiskEngine:
    def __init__(
        self,
        *,
        configuration: RiskConfiguration | None = None,
        configuration_path=None,
        audit: RiskDecisionAudit | None = None,
        kill_switch_path=Path("data/risk_engine/kill_switch.json"),
    ):
        if configuration is not None:
            self.configuration = configuration
        elif configuration_path is not None:
            self.configuration = load_risk_configuration(configuration_path)
        else:
            self.configuration = load_risk_configuration()
        self.audit = audit or RiskDecisionAudit()
        self.kill_switch_path = Path(kill_switch_path)
        self._evaluation_lock = threading.RLock()

    def evaluate(self, proposal: OrderProposal, context: RiskContext) -> RiskDecision:
        with self._evaluation_lock:
            self._evaluation_started = time.perf_counter()
            try:
                return self._evaluate_and_audit(proposal, context)
            except Exception as exc:
                finding = RiskFinding("internal", "unavailable", "INTERNAL_RISK_ERROR", str(exc))
                decision = self._decision(proposal, context, [finding], "INTERNAL_RISK_ERROR", DecisionStatus.BLOCKED)
                try:
                    self.audit.append(proposal, context, decision)
                except Exception:
                    pass
                return decision

    def _evaluate_and_audit(self, proposal: OrderProposal, context: RiskContext) -> RiskDecision:
        existing = self.audit.records_for_proposal(proposal.proposal_id)
        for record in existing:
            prior_proposal = record.get("proposal", {})
            if prior_proposal and record.get("decision", {}).get("proposal_fingerprint") != proposal.fingerprint:
                return self._finish(
                    proposal, context,
                    [RiskFinding("duplicate", "failed", "DUPLICATE_PROPOSAL", "proposal ID was already used for different order content")],
                    "DUPLICATE_PROPOSAL", DecisionStatus.REJECTED,
                )
        if proposal.proposal_id in context.seen_proposal_ids:
            return self._finish(
                proposal, context,
                [RiskFinding("duplicate", "failed", "DUPLICATE_PROPOSAL", "proposal ID is already present in execution state")],
                "DUPLICATE_PROPOSAL", DecisionStatus.REJECTED,
            )

        findings = []
        metadata = self._validate_proposal(proposal, findings)
        if any(item.status == "failed" for item in findings):
            return self._finish(proposal, context, findings, findings[0].reason_code, DecisionStatus.REJECTED)

        if context.runtime_mode == "monitor_only":
            findings.append(RiskFinding("runtime_mode", "failed", "MONITOR_ONLY", "runtime is monitor-only; execution is ineligible"))
            if not context.shadow_mode:
                return self._finish(proposal, context, findings, "MONITOR_ONLY", DecisionStatus.MONITOR_ONLY)

        operational = [
            (self.configuration.trading_enabled and context.trading_enabled, "trading_enabled", "TRADING_DISABLED", "risk and runtime trading controls are not enabled"),
            (self.configuration.limits_approved, "limits_approved", "RISK_LIMITS_UNAPPROVED", "production risk limits require operator approval"),
            (context.runtime_healthy, "runtime_health", "RUNTIME_UNHEALTHY", "runtime is unhealthy"),
            (context.scheduler_healthy, "scheduler_health", "SCHEDULER_UNHEALTHY", "scheduler state is unhealthy"),
            (context.adapter_ready, "adapter_readiness", "BROKER_UNAVAILABLE", "paper execution adapter is unavailable"),
        ]
        for passed, check, code, summary in operational:
            findings.append(RiskFinding(check, "passed" if passed else "failed", "OK" if passed else code, summary))
        kill = load_kill_switch(self.kill_switch_path)
        if kill.active:
            findings.append(RiskFinding("kill_switch", "failed", "KILL_SWITCH_ACTIVE", kill.reason, {"valid": kill.valid, "mode": kill.mode}))
        else:
            findings.append(RiskFinding("kill_switch", "passed", "OK", "kill switch is inactive"))
        failed = next((item for item in findings if item.status == "failed"), None)
        if failed and not context.shadow_mode:
            return self._finish(proposal, context, findings, failed.reason_code, DecisionStatus.BLOCKED)

        self._market_checks(proposal, context, metadata, findings)
        failed = next((item for item in findings if item.status in {"failed", "unavailable"}), None)
        if failed and not context.shadow_mode:
            status = DecisionStatus.BLOCKED if failed.reason_code in BLOCK_REASON_CODES else DecisionStatus.REJECTED
            return self._finish(proposal, context, findings, failed.reason_code, status)

        self._accounting_checks(context, findings)
        failed = next((item for item in findings if item.status in {"failed", "unavailable"}), None)
        if failed and not context.shadow_mode:
            return self._finish(proposal, context, findings, failed.reason_code, DecisionStatus.BLOCKED)

        portfolio_available = not any(
            item.check == "portfolio_state" and item.status == "unavailable"
            for item in findings
        ) and all((
            context.accounting_active,
            context.accounting_verified,
            context.accounting_reconciled,
            context.accounting_base_currency == self.configuration.base_currency,
            context.reference_price is not None,
            not metadata.fx_required or context.fx_rate_to_base is not None,
        ))
        if portfolio_available:
            self._portfolio_checks(proposal, context, metadata, findings)
        else:
            findings.append(RiskFinding(
                "projected_portfolio", "unavailable", "PORTFOLIO_STATE_UNAVAILABLE",
                "projected exposure, affordability, cash and concentration cannot be calculated",
            ))
        failed = next((item for item in findings if item.status in {"failed", "unavailable"}), None)
        if context.shadow_mode:
            primary = next(
                (item.reason_code for item in findings if item.reason_code != "MONITOR_ONLY" and item.status in {"failed", "unavailable"}),
                "MONITOR_ONLY",
            )
            return self._finish(proposal, context, findings, primary, DecisionStatus.MONITOR_ONLY)
        if failed:
            status = DecisionStatus.BLOCKED if failed.reason_code in BLOCK_REASON_CODES else DecisionStatus.REJECTED
            return self._finish(proposal, context, findings, failed.reason_code, status)
        return self._finish(proposal, context, findings, "APPROVED", DecisionStatus.APPROVED)

    def _validate_proposal(self, proposal, findings):
        required_text = {
            "proposal_id": proposal.proposal_id, "strategy_id": proposal.strategy_id,
            "signal_id": proposal.signal_id, "symbol": proposal.symbol, "market": proposal.market,
            "correlation_id": proposal.correlation_id, "expected_execution_currency": proposal.expected_execution_currency,
        }
        if any(not str(value or "").strip() for value in required_text.values()):
            findings.append(RiskFinding("proposal", "failed", "INVALID_PROPOSAL", "required proposal identity fields are missing"))
            return None
        if proposal.side.upper() not in {"BUY", "SELL"}:
            findings.append(RiskFinding("side", "failed", "INVALID_PROPOSAL", "side must be BUY or SELL"))
            return None
        if proposal.quantity <= 0:
            findings.append(RiskFinding("quantity", "failed", "INVALID_QUANTITY", "quantity must be finite and positive"))
            return None
        if proposal.order_type.upper() not in self.configuration.allowed_order_types:
            findings.append(RiskFinding("order_type", "failed", "UNSUPPORTED_ORDER_TYPE", "order type is not allowed"))
            return None
        if proposal.time_in_force.upper() not in self.configuration.allowed_time_in_force:
            findings.append(RiskFinding("time_in_force", "failed", "INVALID_PROPOSAL", "time in force is not allowed"))
            return None
        if proposal.order_type.upper() == "LIMIT" and (proposal.limit_price is None or proposal.limit_price <= 0):
            findings.append(RiskFinding("limit_price", "failed", "INVALID_PROPOSAL", "positive limit price is required"))
            return None
        if proposal.order_type.upper() == "STOP" and (proposal.stop_price is None or proposal.stop_price <= 0):
            findings.append(RiskFinding("stop_price", "failed", "INVALID_PROPOSAL", "positive stop price is required"))
            return None
        try:
            metadata = get_instrument_metadata(proposal.symbol)
        except KeyError:
            findings.append(RiskFinding("instrument", "failed", "UNKNOWN_INSTRUMENT", "instrument is absent from the authoritative registry"))
            return None
        except Exception as exc:
            findings.append(RiskFinding("instrument", "failed", "UNKNOWN_INSTRUMENT", str(exc)))
            return None
        if proposal.market != metadata.exchange:
            findings.append(RiskFinding("market", "failed", "UNSUPPORTED_MARKET", "proposal market does not match verified instrument metadata"))
            return None
        if proposal.expected_execution_currency != metadata.instrument_currency:
            findings.append(RiskFinding("currency", "failed", "INVALID_PROPOSAL", "proposal currency does not match verified instrument metadata"))
            return None
        findings.append(RiskFinding("proposal", "passed", "OK", "proposal and authoritative metadata are valid"))
        return metadata

    def _market_checks(self, proposal, context, metadata, findings):
        if not context.market_session_valid:
            findings.append(RiskFinding("market_session", "failed", "MARKET_CLOSED", "market/session state is invalid for this proposal"))
        if not context.source_bar_complete:
            findings.append(RiskFinding("completed_bar", "failed", "BAR_INCOMPLETE", "source bar is incomplete"))
        if proposal.source_bar_timestamp > context.now or proposal.strategy_timestamp > context.now:
            findings.append(RiskFinding("timestamps", "failed", "FUTURE_MARKET_DATA", "proposal uses future-dated data"))
        key = f"{metadata.market_calendar}:{proposal.metadata.get('timeframe', '1d')}"
        threshold = self.configuration.market_data_max_age_seconds.get(key)
        if threshold is None:
            findings.append(RiskFinding("freshness_policy", "unavailable", "MARKET_DATA_STALE", "no market-specific freshness threshold is configured"))
        if context.reference_price is None or context.reference_price_timestamp is None:
            findings.append(RiskFinding("reference_price", "unavailable", "MARKET_DATA_MISSING", "reference price or timestamp is missing"))
        else:
            price = decimal_value(context.reference_price, "reference_price")
            if price <= 0:
                findings.append(RiskFinding("reference_price", "failed", "MARKET_DATA_MISSING", "reference price must be positive"))
            elif context.reference_price_timestamp > context.now:
                findings.append(RiskFinding("reference_price", "failed", "FUTURE_MARKET_DATA", "reference price is future-dated"))
            elif threshold is not None and (context.now - context.reference_price_timestamp).total_seconds() > threshold:
                findings.append(RiskFinding("reference_price", "failed", "MARKET_DATA_STALE", "reference price exceeds market-specific age limit", {"age_seconds": (context.now-context.reference_price_timestamp).total_seconds()}, {"maximum_age_seconds": threshold}))
            else:
                findings.append(RiskFinding("market_data", "passed", "OK", "market data is complete and fresh"))
        if metadata.fx_required:
            fx_threshold = self.configuration.fx_max_age_seconds.get(metadata.instrument_currency)
            if context.fx_rate_to_base is None or context.fx_timestamp is None:
                findings.append(RiskFinding("fx", "unavailable", "FX_RATE_MISSING", "verified FX quote is required"))
            elif decimal_value(context.fx_rate_to_base, "fx_rate_to_base") <= 0:
                findings.append(RiskFinding("fx", "failed", "FX_RATE_MISSING", "FX rate must be positive"))
            elif context.fx_timestamp > context.now:
                findings.append(RiskFinding("fx", "failed", "FUTURE_MARKET_DATA", "FX quote is future-dated"))
            elif fx_threshold is None or (context.now-context.fx_timestamp).total_seconds() > fx_threshold:
                findings.append(RiskFinding("fx", "failed", "FX_RATE_STALE", "FX quote is stale or lacks a currency-specific policy"))
            else:
                findings.append(RiskFinding("fx", "passed", "OK", "verified FX quote is fresh"))
        else:
            if context.fx_rate_to_base not in {None, Decimal("1")}:
                findings.append(RiskFinding("fx", "failed", "FX_RATE_MISSING", "GBP identity conversion must use rate 1 or no quote"))
            else:
                findings.append(RiskFinding("fx", "passed", "OK", "GBP identity conversion requires no inferred FX"))

    def _accounting_checks(self, context, findings):
        checks = [
            (context.accounting_active, "accounting_active", "ACCOUNTING_INACTIVE", "canonical accounting generation is inactive"),
            (context.accounting_verified, "accounting_verified", "ACCOUNTING_UNVERIFIED", "canonical accounting generation is unverified"),
            (context.accounting_base_currency == self.configuration.base_currency, "base_currency", "ACCOUNTING_UNVERIFIED", "accounting base currency is not configured GBP"),
            (context.accounting_reconciled, "reconciliation", "ACCOUNTING_UNVERIFIED", "canonical accounting is unreconciled"),
        ]
        for passed, check, code, summary in checks:
            findings.append(RiskFinding(check, "passed" if passed else "unavailable", "OK" if passed else code, summary))
        required = {
            "cash_base": context.cash_base, "portfolio_equity_base": context.portfolio_equity_base,
            "positions_base": context.positions_base, "position_quantities": context.position_quantities,
            "open_order_notional_base": context.open_order_notional_base,
            "daily_realised_pnl_base": context.daily_realised_pnl_base,
            "daily_total_pnl_base": context.daily_total_pnl_base,
            "equity_high_water_mark_base": context.equity_high_water_mark_base,
            "strategy_exposure_base": context.strategy_exposure_base,
            "market_exposure_base": context.market_exposure_base,
            "currency_exposure_base": context.currency_exposure_base,
        }
        missing = sorted(name for name, value in required.items() if value is None)
        findings.append(RiskFinding("portfolio_state", "unavailable" if missing else "passed", "PORTFOLIO_STATE_UNAVAILABLE" if missing else "OK", "verified portfolio inputs are missing" if missing else "verified portfolio state is available", {"missing": missing}))

    def _portfolio_checks(self, proposal, context, metadata, findings):
        price = decimal_value(context.reference_price, "reference_price") * metadata.price_scale
        fx = Decimal("1") if not metadata.fx_required else decimal_value(context.fx_rate_to_base, "fx_rate_to_base")
        fees = decimal_value(context.estimated_fees_base, "estimated_fees_base")
        notional = proposal.quantity * price * fx
        positions = {key: decimal_value(value, f"positions_base[{key}]") for key, value in context.positions_base.items()}
        quantities = {key: decimal_value(value, f"position_quantities[{key}]") for key, value in context.position_quantities.items()}
        current = positions.get(proposal.symbol, Decimal("0"))
        held_quantity = quantities.get(proposal.symbol, Decimal("0"))
        reducing = proposal.side.upper() == "SELL"
        if reducing and proposal.quantity > held_quantity:
            findings.append(RiskFinding("sell_quantity", "failed", "SELL_EXCEEDS_POSITION", "sell quantity exceeds verified holding", {"held_quantity": held_quantity, "sell_quantity": proposal.quantity}))
            return
        signed = notional if proposal.side.upper() == "BUY" else -notional
        projected_position = max(Decimal("0"), current + signed)
        equity = decimal_value(context.portfolio_equity_base, "portfolio_equity_base")
        cash = decimal_value(context.cash_base, "cash_base")
        if equity <= 0:
            findings.append(RiskFinding("portfolio_equity", "unavailable", "PORTFOLIO_STATE_UNAVAILABLE", "portfolio equity must be positive"))
            return
        projected_cash = cash - notional - fees if proposal.side.upper() == "BUY" else cash + notional - fees
        projected_positions = dict(positions)
        if projected_position:
            projected_positions[proposal.symbol] = projected_position
        else:
            projected_positions.pop(proposal.symbol, None)
        gross = sum(abs(value) for value in projected_positions.values()) + decimal_value(context.open_order_notional_base, "open_order_notional_base")
        net = sum(projected_positions.values())
        concentration = projected_position / equity
        findings.append(RiskFinding(
            "projected_portfolio", "passed", "OK", "projected post-trade portfolio values calculated",
            {
                "order_notional_base": notional,
                "estimated_fees_base": fees,
                "projected_cash_base": projected_cash,
                "affordability_shortfall_base": max(Decimal("0"), -projected_cash),
                "projected_position_base": projected_position,
                "projected_concentration_ratio": concentration,
                "projected_gross_exposure_base": gross,
                "projected_gross_exposure_ratio": gross / equity,
                "projected_net_exposure_base": net,
                "projected_net_exposure_ratio": abs(net) / equity,
            },
        ))
        if proposal.side.upper() == "BUY" and projected_cash < 0:
            findings.append(RiskFinding("cash", "failed", "INSUFFICIENT_CASH", "post-trade cash would be negative", {"projected_cash_base": projected_cash}))
        limits = self.configuration
        if notional + fees > limits.maximum_order_notional_base:
            findings.append(RiskFinding("order_notional", "failed", "ORDER_NOTIONAL_LIMIT_EXCEEDED", "order notional exceeds limit", {"order_notional_base": notional+fees}, {"maximum": limits.maximum_order_notional_base}))
        if not reducing or not limits.reduction_orders_allowed_when_limits_exceeded:
            if projected_position > limits.maximum_position_notional_base:
                findings.append(RiskFinding("position_notional", "failed", "POSITION_LIMIT_EXCEEDED", "projected position exceeds notional limit"))
            if concentration > limits.maximum_position_ratio:
                findings.append(RiskFinding("concentration", "failed", "CONCENTRATION_LIMIT_EXCEEDED", "projected position exceeds concentration limit"))
        if not reducing or not limits.reduction_orders_allowed_when_limits_exceeded:
            if gross / equity > limits.maximum_gross_exposure_ratio:
                findings.append(RiskFinding("gross_exposure", "failed", "GROSS_EXPOSURE_LIMIT_EXCEEDED", "projected gross exposure exceeds limit"))
            if abs(net) / equity > limits.maximum_net_exposure_ratio:
                findings.append(RiskFinding("net_exposure", "failed", "NET_EXPOSURE_LIMIT_EXCEEDED", "projected net exposure exceeds limit"))
            if proposal.side.upper() == "BUY" and current == 0 and len(projected_positions) > limits.maximum_open_positions:
                findings.append(RiskFinding("open_positions", "failed", "MAX_OPEN_POSITIONS_EXCEEDED", "projected open-position count exceeds limit"))
            strategy_current = decimal_value((context.strategy_exposure_base or {}).get(proposal.strategy_id, 0), "strategy_exposure")
            if (strategy_current + notional) / equity > limits.maximum_strategy_exposure_ratio:
                findings.append(RiskFinding("strategy_exposure", "failed", "POSITION_LIMIT_EXCEEDED", "projected strategy exposure exceeds limit"))
            market_current = decimal_value((context.market_exposure_base or {}).get(proposal.market, 0), "market_exposure")
            if (market_current + notional) / equity > limits.maximum_market_exposure_ratio:
                findings.append(RiskFinding("market_exposure", "failed", "POSITION_LIMIT_EXCEEDED", "projected market exposure exceeds limit"))
            currency_current = decimal_value((context.currency_exposure_base or {}).get(metadata.instrument_currency, 0), "currency_exposure")
            if (currency_current + notional) / equity > limits.maximum_currency_exposure_ratio:
                findings.append(RiskFinding("currency_exposure", "failed", "POSITION_LIMIT_EXCEEDED", "projected currency exposure exceeds limit"))
        daily_realised = decimal_value(context.daily_realised_pnl_base, "daily_realised_pnl_base")
        daily_total = decimal_value(context.daily_total_pnl_base, "daily_total_pnl_base")
        if daily_realised < -limits.maximum_daily_realised_loss_base:
            findings.append(RiskFinding("daily_realised_loss", "failed", "DAILY_LOSS_LIMIT_EXCEEDED", "daily realised loss limit is exceeded"))
        if daily_total < -limits.maximum_daily_total_loss_base:
            findings.append(RiskFinding("daily_total_loss", "failed", "DAILY_LOSS_LIMIT_EXCEEDED", "daily total P&L loss limit is exceeded"))
        hwm = decimal_value(context.equity_high_water_mark_base, "equity_high_water_mark_base")
        if hwm <= 0:
            findings.append(RiskFinding("drawdown", "unavailable", "PORTFOLIO_STATE_UNAVAILABLE", "equity high-water mark is invalid"))
        elif (hwm-equity)/hwm > limits.maximum_drawdown_ratio:
            findings.append(RiskFinding("drawdown", "failed", "DRAWDOWN_LIMIT_EXCEEDED", "portfolio drawdown limit is exceeded"))
        if not any(item.status in {"failed", "unavailable"} for item in findings):
            findings.append(RiskFinding("portfolio_limits", "passed", "OK", "projected post-trade portfolio satisfies configured limits", {"order_notional_base": notional, "projected_cash_base": projected_cash, "projected_gross_base": gross, "projected_net_base": net}))

    def _finish(self, proposal, context, findings, reason, status):
        decision = self._decision(proposal, context, findings, reason, status)
        try:
            self.audit.append(proposal, context, decision)
        except RiskAuditError:
            if decision.approved:
                failure = list(findings) + [RiskFinding("audit", "unavailable", "AUDIT_WRITE_FAILED", "approved decision could not be durably audited")]
                return self._decision(proposal, context, failure, "AUDIT_WRITE_FAILED", DecisionStatus.BLOCKED)
            raise
        return decision

    def _decision(self, proposal, context, findings, reason, status):
        timestamp = context.now
        expires = timestamp + timedelta(seconds=self.configuration.decision_expiry_seconds)
        proposal_fingerprint = self._safe_fingerprint(proposal)
        context_fingerprint = self._safe_fingerprint(context)
        material = f"{proposal_fingerprint}|{context_fingerprint}|{self.configuration.configuration_hash}|{timestamp.isoformat()}"
        decision_id = hashlib.sha256(material.encode("utf-8")).hexdigest()
        passed = tuple(item.check for item in findings if item.status == "passed")
        failed = tuple(item.check for item in findings if item.status == "failed")
        unavailable = tuple(item.check for item in findings if item.status == "unavailable")
        return RiskDecision(
            decision_id=decision_id, proposal_id=proposal.proposal_id, status=status,
            approved=status is DecisionStatus.APPROVED, timestamp=timestamp, expires_at=expires,
            primary_reason_code=reason, summary="Order approved by central pre-trade risk engine" if status is DecisionStatus.APPROVED else f"Order not approved: {reason}",
            findings=tuple(findings), checks_performed=tuple(item.check for item in findings),
            checks_passed=passed, checks_failed=failed, checks_unavailable=unavailable,
            relevant_limits=self.configuration.limits(), observed_values={
                "runtime_mode": context.runtime_mode,
                "shadow_mode": context.shadow_mode,
                "execution_eligible": False if context.shadow_mode else status is DecisionStatus.APPROVED,
                **{
                    key: value
                    for item in findings
                    if item.check == "projected_portfolio"
                    for key, value in item.observed.items()
                },
            },
            software_version=SOFTWARE_VERSION, configuration_version=self.configuration.configuration_version,
            configuration_hash=self.configuration.configuration_hash, proposal_fingerprint=proposal_fingerprint,
            context_fingerprint=context_fingerprint, accounting_generation_id=context.accounting_generation_id,
            market_data_timestamps={
                "source_bar": self._safe_timestamp(proposal.source_bar_timestamp),
                "reference_price": self._safe_timestamp(context.reference_price_timestamp),
                "fx": self._safe_timestamp(context.fx_timestamp),
            },
            correlation_id=proposal.correlation_id,
            evaluation_latency_ms=Decimal(str(round((time.perf_counter() - self._evaluation_started) * 1000, 3))),
        )

    @staticmethod
    def _safe_timestamp(value):
        return value.isoformat() if hasattr(value, "isoformat") else None

    @staticmethod
    def _safe_fingerprint(value):
        try:
            return value.fingerprint
        except Exception:
            return "unavailable"
