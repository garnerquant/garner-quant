from __future__ import annotations

import json
from pathlib import Path

from risk_engine.audit import DEFAULT_AUDIT_PATH
from risk_engine.configuration import RiskConfigurationError, load_risk_configuration
from risk_engine.kill_switch import load_kill_switch


def load_risk_diagnostics(
    *,
    configuration_path=None,
    kill_switch_path=Path("data/risk_engine/kill_switch.json"),
    audit_path=DEFAULT_AUDIT_PATH,
) -> dict:
    try:
        config = load_risk_configuration(configuration_path) if configuration_path else load_risk_configuration()
        configuration_loaded = True
        configuration_error = None
    except RiskConfigurationError as exc:
        config = None
        configuration_loaded = False
        configuration_error = str(exc)
    kill = load_kill_switch(kill_switch_path)
    latest = None
    counts = {"APPROVED": 0, "REJECTED": 0, "BLOCKED": 0, "MONITOR_ONLY": 0}
    try:
        for line in Path(audit_path).read_text(encoding="utf-8").splitlines() if Path(audit_path).exists() else []:
            record = json.loads(line)
            decision = record.get("decision", {})
            status = decision.get("status")
            if status in counts:
                counts[status] += 1
            latest = decision
        audit_error = None
    except Exception:
        audit_error = "risk decision audit is unreadable"
    if not configuration_loaded or audit_error or not kill.valid:
        engine_status = "ERROR"
    elif kill.active or config.trading_enabled is not True or config.limits_approved is not True:
        engine_status = "BLOCKED"
    else:
        engine_status = "ACTIVE"
    return {
        "engine_status": engine_status,
        "configuration_loaded": configuration_loaded,
        "configuration_version": config.configuration_version if config else None,
        "configuration_error": configuration_error,
        "kill_switch_active": kill.active,
        "kill_switch_valid": kill.valid,
        "trading_enabled": config.trading_enabled if config else False,
        "limits_approved": config.limits_approved if config else False,
        "latest_decision": latest,
        "decision_counts": counts,
        "audit_error": audit_error,
    }
