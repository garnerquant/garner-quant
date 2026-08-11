"""Pure presentation labels for the status of project evidence."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceLabel:
    status: str
    title: str
    warning: str
    severity: str


_LABELS = {
    "legacy_methodologically_invalid": EvidenceLabel(
        "legacy_methodologically_invalid",
        "Legacy result — methodologically invalid",
        "These historical results are not suitable for investment decisions. "
        "The existing backtest applies present-day/current fundamental data "
        "across historical dates and does not match the paper-trading execution "
        "model. Reported returns and risk statistics remain unverified.",
        "error",
    ),
    "legacy_unverified": EvidenceLabel(
        "legacy_unverified",
        "Exploratory legacy research — unverified",
        "This research may depend on the contaminated historical methodology. "
        "It is suitable for software exploration only and must not be treated "
        "as validated investment evidence.",
        "warning",
    ),
    "paper_observation_unverified": EvidenceLabel(
        "paper_observation_unverified",
        "Paper observation — unverified",
        "Paper-trading results are operational observations, not proof of "
        "strategy validity or expected live performance.",
        "warning",
    ),
    "accounting_evidence_not_quantitative_validation": EvidenceLabel(
        "accounting_evidence_not_quantitative_validation",
        "Accounting/operational evidence only",
        "Successful reconciliation or runtime operation does not validate the "
        "investment strategy or its historical performance.",
        "info",
    ),
    "operational_evidence_not_quantitative_validation": EvidenceLabel(
        "operational_evidence_not_quantitative_validation",
        "Accounting/operational evidence only",
        "Successful reconciliation or runtime operation does not validate the "
        "investment strategy or its historical performance.",
        "info",
    ),
}


def evidence_label(status: str) -> EvidenceLabel:
    """Return a fail-closed, deterministic presentation label."""
    return _LABELS.get(status, _LABELS["legacy_unverified"])
