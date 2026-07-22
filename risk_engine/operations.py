from __future__ import annotations

import json
from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from dashboard.accounting_reader import load_dashboard_accounting_status
from risk_engine.audit import DEFAULT_AUDIT_PATH
from risk_engine.configuration import RiskConfigurationError, load_risk_configuration
from risk_engine.kill_switch import DEFAULT_AUDIT_PATH as KILL_AUDIT_PATH, load_kill_switch


def _records(path=DEFAULT_AUDIT_PATH):
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"risk audit is malformed at line {number}") from exc
        if not all(key in payload for key in ("proposal", "context", "decision")):
            raise ValueError(f"risk audit record {number} is incomplete")
        records.append(payload)
    return records


def decision_history(*, audit_path=DEFAULT_AUDIT_PATH, strategy=None, symbol=None,
                     decision=None, reason=None, date=None):
    rows = []
    for record in _records(audit_path):
        proposal, context, result = record["proposal"], record["context"], record["decision"]
        observed = result.get("observed_values") or {}
        timestamp = str(result.get("timestamp") or "")
        row = {
            "time": timestamp, "strategy": proposal.get("strategy_id"),
            "symbol": proposal.get("symbol"), "market": proposal.get("market"),
            "side": proposal.get("side"), "quantity": proposal.get("quantity"),
            "price": context.get("reference_price"), "fx_rate": context.get("fx_rate_to_base"),
            "accounting_state": "ACTIVE" if context.get("accounting_active") and context.get("accounting_verified") else "PENDING",
            "portfolio_state": "AVAILABLE" if context.get("portfolio_equity_base") is not None else "UNAVAILABLE",
            "decision": result.get("status"), "reason": result.get("primary_reason_code"),
            "failed_checks": ", ".join(result.get("checks_failed") or []),
            "projected_exposure": observed.get("projected_gross_exposure_base"),
            "projected_cash": observed.get("projected_cash_base"),
            "projected_net": observed.get("projected_net_exposure_base"),
            "projected_concentration": observed.get("projected_concentration_ratio"),
            "affordability_shortfall": observed.get("affordability_shortfall_base"),
            "drawdown": _finding_value(result, "drawdown"),
            "daily_loss": context.get("daily_total_pnl_base"),
            "latency_ms": result.get("evaluation_latency_ms"),
            "configuration_version": result.get("configuration_version"),
            "execution_eligible": observed.get("execution_eligible", False),
        }
        if strategy and row["strategy"] != strategy: continue
        if symbol and row["symbol"] != symbol: continue
        if decision and row["decision"] != decision: continue
        if reason and row["reason"] != reason: continue
        if date and not timestamp.startswith(str(date)): continue
        rows.append(row)
    return rows


def _finding_value(decision, check):
    for finding in decision.get("findings") or []:
        if finding.get("check") == check:
            return finding.get("observed") or finding.get("status")
    return None


def risk_metrics(*, audit_path=DEFAULT_AUDIT_PATH, kill_audit_path=KILL_AUDIT_PATH, now=None):
    rows = decision_history(audit_path=audit_path)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    today = [row for row in rows if str(row["time"]).startswith(current)]
    counts = {name: sum(row["decision"] == name for row in today) for name in ("APPROVED", "REJECTED", "BLOCKED", "MONITOR_ONLY")}
    total = len(today)
    reasons = {}
    for row in today:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    latencies = [Decimal(str(row["latency_ms"])) for row in today if row["latency_ms"] is not None]
    exposures = [Decimal(str(row["projected_exposure"])) for row in today if row["projected_exposure"] is not None]
    shortfalls = [Decimal(str(row["affordability_shortfall"])) for row in today if row["affordability_shortfall"] is not None]
    kill_activations = 0
    try:
        for line in Path(kill_audit_path).read_text(encoding="utf-8").splitlines() if Path(kill_audit_path).exists() else []:
            payload = json.loads(line)
            if str(payload.get("timestamp", "")).startswith(current) and payload.get("new_state", {}).get("active") is True:
                kill_activations += 1
    except Exception:
        kill_activations = None
    return {
        "date": current, "total": total, **counts,
        "approval_rate": counts["APPROVED"] / total if total else 0,
        "rejection_rate": counts["REJECTED"] / total if total else 0,
        "blocked_rate": counts["BLOCKED"] / total if total else 0,
        "top_rejection_reasons": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:10]),
        "average_latency_ms": str(sum(latencies) / len(latencies)) if latencies else None,
        "highest_projected_exposure_base": str(max(exposures)) if exposures else None,
        "largest_affordability_shortfall_base": str(max(shortfalls)) if shortfalls else None,
        "stale_data_occurrences": reasons.get("MARKET_DATA_STALE", 0),
        "fx_failures": reasons.get("FX_RATE_MISSING", 0) + reasons.get("FX_RATE_STALE", 0),
        "scheduler_failures": reasons.get("SCHEDULER_UNHEALTHY", 0),
        "runtime_failures": reasons.get("RUNTIME_UNHEALTHY", 0),
        "kill_switch_activations": kill_activations,
        "configuration_changes": max(0, len({row["configuration_version"] for row in rows}) - 1),
        "last_evaluation_timestamp": rows[-1]["time"] if rows else None,
    }


def configuration_health(configuration_path=None):
    try:
        config = load_risk_configuration(configuration_path) if configuration_path else load_risk_configuration()
    except RiskConfigurationError as exc:
        return {"healthy": False, "error": str(exc), "fields": []}
    monetary = {name for name in config.__dataclass_fields__ if name.endswith("_base")}
    ratios = {name for name in config.__dataclass_fields__ if name.endswith("_ratio")}
    rows = []
    for item in fields(config):
        name, value = item.name, getattr(config, item.name)
        unit = "GBP" if name in monetary else "decimal ratio" if name in ratios else "seconds" if name.endswith("_seconds") else "count" if name == "maximum_open_positions" else "policy"
        rows.append({"field": name, "value": str(value), "unit": unit, "valid": True,
                     "used": name not in {"schema_version", "kill_switch_allows_reductions"}})
    return {
        "healthy": True, "error": None, "fields": rows,
        "configuration_version": config.configuration_version,
        "configuration_hash": config.configuration_hash,
        "override_hierarchy": "single strict production configuration; no implicit overrides",
    }


def activation_readiness(*, accounting_root=Path("data/accounting_generations"), configuration_path=None,
                         kill_switch_path=Path("data/risk_engine/kill_switch.json"),
                         runtime_config_path=Path("runtime/live_runtime_config.json")):
    blockers = []
    config_report = configuration_health(configuration_path)
    if not config_report["healthy"]:
        blockers.append(_blocker("CRITICAL", "Risk configuration invalid", config_report["error"], "Repair and revalidate configuration while trading remains disabled."))
        config = None
    else:
        config = load_risk_configuration(configuration_path) if configuration_path else load_risk_configuration()
    accounting = load_dashboard_accounting_status(accounting_root)
    kill = load_kill_switch(kill_switch_path)
    try:
        runtime = json.loads(Path(runtime_config_path).read_text(encoding="utf-8"))
    except Exception:
        runtime = {}
    if accounting.state != "active": blockers.append(_blocker("CRITICAL", "Accounting inactive", accounting.reason or "No active verified canonical GBP generation.", "Complete the existing canonical accounting publication and reconciliation process."))
    if config and not config.limits_approved: blockers.append(_blocker("HIGH", "Risk limits not approved", config.configuration_version, "Obtain independent operator approval for every configured limit."))
    if config and not config.trading_enabled: blockers.append(_blocker("HIGH", "Risk trading control disabled", "trading_enabled=false", "Retain disabled until all readiness blockers are cleared."))
    if kill.active: blockers.append(_blocker("HIGH", "Kill switch active", kill.reason, "Investigate and clear only through the audited operator procedure after readiness review."))
    if runtime.get("mode") != "paper_execution": blockers.append(_blocker("HIGH", "Runtime is monitor-only", f"mode={runtime.get('mode', 'unavailable')}", "Retain monitor-only until every independent readiness blocker is resolved."))
    if runtime.get("paper_execution_enabled") is not True: blockers.append(_blocker("HIGH", "Paper execution disabled", "paper_execution_enabled is not true", "Retain disabled throughout shadow observation and readiness review."))
    blockers.append(_blocker("CRITICAL", "Canonical strategy exposure unavailable", "Production context intentionally supplies no canonical strategy exposure.", "Add authoritative strategy attribution to canonical accounting and validate it."))
    blockers.append(_blocker("HIGH", "Drawdown model incomplete", "No authoritative deposit/withdrawal adjustment is available.", "Publish verified cash-flow-adjusted canonical equity history."))
    return {"ready": False, "answer": "No", "blockers": blockers, "generated_at": datetime.now(timezone.utc).isoformat()}


def _blocker(severity, description, evidence, action):
    return {"severity": severity, "description": description, "evidence": evidence, "recommended_action": action}
