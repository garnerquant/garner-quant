from __future__ import annotations

from datetime import datetime, timezone

from risk_engine.configuration import RiskConfiguration
from risk_engine.models import DecisionStatus, OrderProposal, RiskDecision


class RiskAuthorizationError(RuntimeError):
    pass


def verify_risk_authorization(
    proposal: OrderProposal,
    decision: RiskDecision,
    *,
    configuration: RiskConfiguration,
    now=None,
) -> None:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise RiskAuthorizationError("authorization clock must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    failures = []
    if decision.status is not DecisionStatus.APPROVED or decision.approved is not True:
        failures.append("decision is not explicitly approved")
    if decision.proposal_id != proposal.proposal_id:
        failures.append("approval proposal ID mismatch")
    if decision.proposal_fingerprint != proposal.fingerprint:
        failures.append("approval does not match exact proposal")
    if decision.configuration_hash != configuration.configuration_hash:
        failures.append("approval configuration mismatch")
    if instant > decision.expires_at:
        failures.append("approval expired")
    if decision.timestamp > instant:
        failures.append("approval timestamp is future-dated")
    if failures:
        raise RiskAuthorizationError("; ".join(failures))
