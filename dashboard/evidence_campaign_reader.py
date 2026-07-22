"""Fail-closed, read-only adapter for the current evidence campaign."""
from pathlib import Path

from canonical_accounting.evidence_campaign import build_campaign, campaign_reports
from canonical_accounting.frozen_evidence import FrozenEvidenceError, load_frozen_evidence_history


def evidence_campaign_status(root: str | Path = "data/frozen_evidence_packs") -> dict:
    try:
        history = load_frozen_evidence_history(root)
        pack = history[-1]
        campaign = build_campaign(pack, title="Opening Snapshot Evidence Campaign", owner="Operator",
                                  created=pack.creation_timestamp, history=history)
        reports = campaign_reports(campaign)
        return {
            "status": campaign.status, "campaign_id": campaign.campaign_id, "title": campaign.title,
            "cutoff": campaign.cutoff_date.isoformat(), "created": campaign.created.isoformat(),
            "coverage": str(campaign.coverage), "priority": campaign.priority, "owner": campaign.owner,
            "readiness": campaign.readiness.state, "readiness_reasons": campaign.readiness.reasons,
            "critical_blockers": len(reports["critical_blockers"]),
            "recently_imported": campaign.recently_imported,
            "outstanding_conflicts": campaign.outstanding_conflicts,
            "resolved_this_campaign": campaign.resolved_this_campaign,
            "coverage_trend": tuple((point.timestamp.isoformat(), str(point.completion)) for point in campaign.timeline),
            "estimated_remaining_work": campaign.estimated_remaining_work,
            "requirements": tuple(_requirement(item) for item in campaign.requirements),
            "positions": tuple(_position(item) for item in campaign.positions),
            "cash": tuple({"Category": item.category, "Status": item.state, "Reason": item.reason} for item in campaign.cash),
            "priorities": tuple({"Rank": item.rank, "Work": item.title, "Severity": item.severity,
                                  "Status": item.state, "Reason": item.reason} for item in campaign.priorities),
            "bundle_hash": campaign.bundle_hash,
        }
    except (FrozenEvidenceError, ValueError, OSError) as exc:
        return {"status": "NOT_AVAILABLE", "coverage": None, "readiness": "NOT_READY",
                "critical_blockers": None, "estimated_remaining_work": None, "error": str(exc)}


def _requirement(item):
    return {"Requirement": item.label, "Status": item.state, "Critical": item.critical, "Reason": item.reason}


def _position(item):
    return {"Position": item.symbol, "Strategy": item.strategy_attribution, "FIFO": item.fifo,
            "Acquisition FX": item.acquisition_fx, "Cash Linkage": item.cash_linkage,
            "Corporate Actions": item.corporate_actions, "Confidence": item.evidence_confidence,
            "Status": item.status}
