"""Immutable, deterministic research foundation models."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "continuous-research-v1"
GENERATOR_VERSION = "initial-foundation-v1"
OBSERVATION_TYPES = frozenset({"PERFORMANCE_DIFFERENCE", "LOSS_CONCENTRATION", "WIN_CONCENTRATION",
    "REGIME_EFFECT", "ENTRY_CHARACTERISTIC", "EXIT_CHARACTERISTIC", "HOLDING_PERIOD_EFFECT",
    "RISK_REJECTION_OUTCOME", "MISSED_OPPORTUNITY", "STRATEGY_OVERLAP", "EXECUTION_EFFECT",
    "DRAWDOWN_PATTERN", "STABILITY_WARNING", "DATA_QUALITY_WARNING", "OTHER"})
EVIDENCE_QUALITY = frozenset({"INSUFFICIENT", "WEAK", "EXPLORATORY", "MODERATE", "STRONG"})
CAUSAL_TERMS = (" caused ", " will improve", " proves ", " should be added")


def json_value(value: Any) -> Any:
    if isinstance(value, datetime): return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, tuple): return [json_value(item) for item in value]
    if isinstance(value, dict): return {str(key): json_value(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"): return json_value(asdict(value))
    return value


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None: raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class FeatureDefinition:
    feature_name: str
    meaning: str
    source_fields: tuple[str, ...]
    valid_values: tuple[str, ...]
    missing_value_policy: str
    calculation_version: str
    look_ahead_safety_rule: str
    leakage_risk: str
    minimum_evidence_requirement: int


@dataclass(frozen=True)
class ResearchObservation:
    observation_id: str
    observation_type: str
    title: str
    description: str
    source_population: str
    strategy_scope: tuple[str, ...]
    instrument_scope: tuple[str, ...]
    market_scope: tuple[str, ...]
    observation_period: tuple[str, str]
    comparison_groups: tuple[str, ...]
    sample_size: int
    observed_metric: tuple[str, str]
    control_metric: tuple[str, str]
    absolute_difference: str
    relative_difference: str | None
    uncertainty_information: tuple[tuple[str, str], ...]
    evidence_quality: str
    limitations: tuple[str, ...]
    provenance_references: tuple[str, ...]
    generated_at: datetime
    generator_version: str
    attempted_comparisons: int
    raw_significance: str | None
    adjusted_significance: str | None
    status: str = "OBSERVED"

    def __post_init__(self):
        if self.observation_type not in OBSERVATION_TYPES: raise ValueError("invalid observation_type")
        if self.evidence_quality not in EVIDENCE_QUALITY: raise ValueError("invalid evidence_quality")
        aware(self.generated_at, "generated_at")
        text = f" {self.description.lower()} "
        if any(term in text for term in CAUSAL_TERMS): raise ValueError("observation uses unsupported causal language")
        material = asdict(self); material.pop("observation_id")
        expected = "obs-" + stable_hash(material)[:24]
        if self.observation_id != expected: raise ValueError("observation_id is not deterministic")

    @property
    def content_hash(self): return stable_hash(asdict(self))


def make_observation(**values) -> ResearchObservation:
    values = dict(values); values["generated_at"] = aware(values["generated_at"], "generated_at")
    values.setdefault("generator_version", GENERATOR_VERSION); values.setdefault("status", "OBSERVED")
    material = dict(values); material.pop("observation_id", None)
    values["observation_id"] = "obs-" + stable_hash(material)[:24]
    return ResearchObservation(**values)
