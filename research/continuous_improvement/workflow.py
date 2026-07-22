"""Advisory hypothesis, priority, task and morning-report layers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime

from .analysis import analyse_patterns
from .evidence import ResearchEvidenceSnapshot
from .models import GENERATOR_VERSION, SCHEMA_VERSION, ResearchObservation, aware, stable_hash

HYPOTHESIS_STATES = frozenset({"OBSERVED", "TRIAGED", "PRIORITISED", "EXPERIMENT_SPECIFIED", "EXPERIMENTING",
    "VALIDATED", "REJECTED", "INCONCLUSIVE", "ARCHIVED", "IMPROVEMENT_PROPOSED",
    "APPROVED_FOR_DEPLOYMENT_REVIEW", "IMPLEMENTED", "RETIRED"})


@dataclass(frozen=True)
class ResearchHypothesis:
    hypothesis_id: str; predecessor_id: str | None; observation_ids: tuple[str, ...]; title: str
    hypothesis_statement: str; rationale: str; strategy_scope: tuple[str, ...]; market_scope: tuple[str, ...]
    target_metric: str; proposed_independent_variable: str; proposed_control: str; expected_direction: str
    evidence_strength: str; sample_size: int; limitations: tuple[str, ...]; data_requirements: tuple[str, ...]
    proposed_experiment_type: str; proposed_experiment: str; falsification_condition: str
    priority_score: str; priority_components: tuple[tuple[str, str], ...]; novelty_score: str
    estimated_research_cost: str; expected_information_value: str; duplication_status: str
    lifecycle_status: str; created_at: datetime; generator_version: str = GENERATOR_VERSION
    @property
    def content_hash(self): return stable_hash(asdict(self))


@dataclass(frozen=True)
class ResearchTask:
    task_id: str; hypothesis_id: str; title: str; objective: str; priority: int; owner: str
    status: str; required_inputs: tuple[str, ...]; expected_outputs: tuple[str, ...]
    estimated_complexity: str; proposed_experiment: str; safety_constraints: tuple[str, ...]
    created_at: datetime; due_date: str | None = None
    @property
    def content_hash(self): return stable_hash(asdict(self))


@dataclass(frozen=True)
class MorningResearchReport:
    report_id: str; schema_version: str; artifact_type: str; predecessor_id: str | None
    evidence_snapshot_id: str; evidence_snapshot_hash: str; evidence_cutoff: datetime; created_at: datetime
    observations: tuple[ResearchObservation, ...]; hypotheses: tuple[ResearchHypothesis, ...]
    suggested_tasks: tuple[ResearchTask, ...]; executive_summary: str; trade_review: tuple[tuple[str, str], ...]
    signal_review: tuple[tuple[str, str], ...]; strategy_review: tuple[tuple[str, str], ...]
    important_limitations: tuple[str, ...]; attempted_comparisons: int; generator_version: str = GENERATOR_VERSION
    @property
    def content_hash(self): return stable_hash(asdict(self))


def _priority(observation):
    quality = {"STRONG": 35, "MODERATE": 28, "EXPLORATORY": 18, "WEAK": 8, "INSUFFICIENT": 0}[observation.evidence_quality]
    sample = min(20, observation.sample_size // 5); breadth = min(15, len(observation.instrument_scope) * 3)
    leakage = 15; cost = 8; total = min(100, quality + sample + breadth + leakage + cost)
    return total, (("evidence_quality", str(quality)), ("sample_size", str(sample)), ("instrument_breadth", str(breadth)),
                   ("leakage_safety", str(leakage)), ("research_cost", str(cost)))


def generate_hypotheses(observations, *, created_at, prior_hypotheses=()):
    created_at = aware(created_at, "created_at")
    prior_titles = [str(item.get("title", "") if isinstance(item, dict) else item.title).casefold() for item in prior_hypotheses]
    values = []
    for observation in observations:
        if observation.evidence_quality in {"INSUFFICIENT", "WEAK"}: continue
        group = observation.comparison_groups[0]; total, components = _priority(observation)
        title = f"Test {group} as a controlled strategy condition"
        title_tokens = set(title.casefold().split())
        similarities = [(len(title_tokens & set(value.split())) / len(title_tokens | set(value.split())))
                        for value in prior_titles if value]
        duplicate = ("DUPLICATE" if title.casefold() in prior_titles else
                     "SEMANTICALLY_SIMILAR" if similarities and max(similarities) >= .75 else "NOVEL")
        if observation.observation_type == "HOLDING_PERIOD_EFFECT":
            statement = f"A predeclared time-based exit around {group} may change out-of-sample risk-adjusted return relative to the existing exit rules."
            independent = "time_based_exit"; experiment_type = "exit_rule_comparison"
            experiment = f"Compare the unchanged baseline exits with one predeclared {group} time-based exit using walk-forward validation."
        elif observation.observation_type == "EXIT_CHARACTERISTIC":
            statement = f"A predeclared {group} exit-rule variant may change out-of-sample risk-adjusted return relative to existing exits."
            independent = group; experiment_type = "exit_rule_comparison"
            experiment = f"Compare unchanged baseline exits with one predeclared {group} variant using walk-forward validation."
        else:
            statement = f"A predeclared {group} condition may change out-of-sample risk-adjusted return relative to the existing strategy."
            independent = group; experiment_type = "baseline_vs_one_filter"
            experiment = f"Compare the unchanged baseline with one predeclared {group} filter using walk-forward validation."
        material = {"observation_ids": (observation.observation_id,), "title": title, "created_at": created_at}
        values.append(ResearchHypothesis("hyp-"+stable_hash(material)[:24], None, (observation.observation_id,), title, statement,
            f"The supporting observation showed an association in {observation.sample_size} completed trades; it is not a causal conclusion.",
            observation.strategy_scope, observation.market_scope, "out_of_sample_risk_adjusted_return", independent,
            observation.comparison_groups[1], "to be tested", observation.evidence_quality, observation.sample_size,
            observation.limitations, ("frozen trade evidence", "untouched out-of-sample period", "transaction cost assumptions"),
            experiment_type, experiment,
            "Reject if the candidate fails the predefined out-of-sample acceptance criteria after costs.", str(total), components,
            "50" if duplicate == "NOVEL" else "0", "LOW", "MODERATE", duplicate, "OBSERVED", created_at))
    return tuple(sorted(values, key=lambda item: (-int(item.priority_score), item.hypothesis_id)))


def transition_hypothesis(value, status, *, created_at):
    if status not in HYPOTHESIS_STATES: raise ValueError("invalid hypothesis lifecycle status")
    material = {"predecessor": value.hypothesis_id, "status": status, "created_at": aware(created_at, "created_at")}
    return replace(value, hypothesis_id="hyp-"+stable_hash(material)[:24], predecessor_id=value.hypothesis_id,
                   lifecycle_status=status, created_at=aware(created_at, "created_at"))


def create_tasks(hypotheses, *, created_at, owner="Research Operator"):
    tasks = []
    novel = [item for item in hypotheses if item.duplication_status == "NOVEL"][:3]
    for rank, hypothesis in enumerate(novel, 1):
        material = {"hypothesis": hypothesis.hypothesis_id, "rank": rank, "created_at": created_at}
        tasks.append(ResearchTask("task-"+stable_hash(material)[:24], hypothesis.hypothesis_id, hypothesis.title,
            "Design a frozen experiment specification that can falsify the hypothesis.", rank, owner, "PROPOSED",
            hypothesis.data_requirements, ("frozen experiment specification", "validation plan"), "LOW",
            hypothesis.proposed_experiment, ("Manual approval required before experiment execution", "No production strategy writes",
            "No execution, risk, portfolio, or accounting side effects"), aware(created_at, "created_at")))
    return tuple(tasks)


def build_morning_report(snapshot: ResearchEvidenceSnapshot, *, created_at, predecessor_id=None, prior_hypotheses=()):
    observations, unsupported, attempts = analyse_patterns(snapshot, generated_at=created_at)
    observations = observations[:5]; hypotheses = generate_hypotheses(observations, created_at=created_at, prior_hypotheses=prior_hypotheses)[:3]
    tasks = create_tasks(hypotheses, created_at=created_at)
    completed = sum(item.evidence_type == "COMPLETED_TRADE" for item in snapshot.records)
    decisions = sum(item.evidence_type == "MONITOR_DECISION" for item in snapshot.records)
    limitations = tuple((list(unsupported) + [f"Unavailable evidence: {item}" for item in snapshot.unsupported_fields])[:3])
    summary = (f"{len(observations)} exploratory observation(s) and {len(hypotheses)} falsifiable hypothesis/hypotheses were identified. Human review is required."
               if hypotheses else "No sufficiently robust new research hypotheses were identified.")
    material = {"snapshot": snapshot.snapshot_id, "created_at": created_at, "predecessor": predecessor_id}
    return MorningResearchReport("morning-"+stable_hash(material)[:24], SCHEMA_VERSION, "MORNING_RESEARCH_REPORT", predecessor_id,
        snapshot.snapshot_id, snapshot.content_hash, snapshot.source_cutoff, aware(created_at, "created_at"), observations,
        hypotheses, tasks, summary, (("completed_trades", str(completed)),), (("monitor_decisions", str(decisions)),),
        (("strategies_observed", str(len({value for item in snapshot.records for key,value in item.fields if key=='strategy' and value}))),),
        limitations, attempts)
