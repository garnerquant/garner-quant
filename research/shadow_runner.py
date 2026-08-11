"""Pure, non-authoritative assembly of a shadow research comparison.

The runner accepts only already-constructed contracts.  It does not discover
evidence, consult providers, publish artifacts, or communicate with runtime
or execution code.  A successful result is an observation of agreement or
difference, never a validation or authorization decision.
"""

from dataclasses import dataclass, fields, field, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
import unicodedata

from research.legacy_observations import (
    LegacyObservationSet,
    LegacySignalObservation,
    LegacyWeightObservation,
)
from research.shadow_comparison import (
    InstrumentComparison,
    ShadowComparisonPolicy,
    ShadowComparisonSummary,
    compare_shadow_observations,
)
from strategy.contract import StrategyDecision


SCHEMA_VERSION = 1
RESULT_CLASSIFICATION = "shadow_observation_unverified"
SUPPORTED_POLICIES = frozenset({("shadow", "1")})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonblank")
    return unicodedata.normalize("NFC", value)


def _utc(value, name):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timezone.utc.utcoffset(value)
    ):
        raise ValueError(f"{name} must be timezone-aware UTC")
    return value


def _canonical(value):
    """Return a JSON-compatible canonical value without external state."""
    if isinstance(value, Enum):
        return _canonical(value.value)
    if value is None or isinstance(value, (str, int, bool)):
        return unicodedata.normalize("NFC", value) if isinstance(value, str) else value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal")
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, datetime):
        _utc(value, "datetime")
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical mappings require string keys")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("canonical mapping keys must be unique")
            normalized[normalized_key] = _canonical(item)
        return normalized
    if is_dataclass(value):
        return {
            item.name: _canonical(getattr(value, item.name))
            for item in fields(value)
        }
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _json_bytes(value):
    return json.dumps(
        _canonical(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value):
    """Hash a supported immutable contract or canonical payload."""
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _hash_payload(payload):
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def validated_evidence_identity(decisions):
    """Return the deterministic identity used for a decision evidence set."""
    ordered = _normalize_decisions(decisions)
    return _hash_payload({
        "contract_type": "validated_shadow_evidence",
        "schema_version": SCHEMA_VERSION,
        "decisions": ordered,
    })


def _require_hash(value, name):
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _ordered_unique_text(values, name):
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be an immutable tuple")
    normalized = tuple(_text(value, name) for value in values)
    return tuple(sorted(set(normalized)))


def _normalize_decisions(values):
    if values is None:
        return ()
    if not isinstance(values, tuple):
        raise TypeError("validated_decisions must be an immutable tuple")
    by_id = {}
    by_instrument = {}
    for decision in values:
        if not isinstance(decision, StrategyDecision):
            raise TypeError("validated_decisions must contain StrategyDecision values")
        prior_id = by_id.get(decision.decision_id)
        if prior_id is not None and prior_id != decision:
            raise ValueError("conflicting duplicate validated decision identity")
        prior_instrument = by_instrument.get(decision.instrument_id)
        if prior_instrument is not None and prior_instrument != decision:
            raise ValueError("conflicting validated decisions for one instrument")
        by_id[decision.decision_id] = decision
        by_instrument[decision.instrument_id] = decision
    return tuple(sorted(by_id.values(), key=lambda item: (item.instrument_id, item.decision_id)))


def _bundle_decisions(bundle):
    if bundle is None:
        return None
    if isinstance(bundle, tuple):
        return bundle
    for name in ("validated_decisions", "decisions"):
        candidate = getattr(bundle, name, None)
        if candidate is not None:
            return tuple(candidate)
    raise TypeError("validated_evidence_bundle must expose immutable decisions")


@dataclass(frozen=True, slots=True, init=False)
class ShadowRunRequest:
    """All inputs required for one deterministic shadow comparison."""

    schema_version: int
    shadow_run_id: str
    created_at: datetime
    information_cutoff: datetime
    validated_decisions: tuple[StrategyDecision, ...]
    validated_evidence_identity: str
    legacy_observations: LegacyObservationSet | None
    comparison_policy: ShadowComparisonPolicy
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    code_version: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    validated_evidence_bundle: tuple[StrategyDecision, ...] | None

    def __init__(
        self,
        schema_version,
        shadow_run_id,
        created_at,
        information_cutoff,
        validated_decisions=None,
        validated_evidence_identity=None,
        legacy_observations=None,
        comparison_policy=None,
        strategy_id=None,
        strategy_version=None,
        parameter_set_id=None,
        code_version=None,
        warnings=(),
        limitations=(),
        *,
        validated_evidence_bundle=None,
        validated_evidence_hash=None,
        parameter_version=None,
        code_revision=None,
        legacy_observation_set=None,
    ):
        if validated_evidence_identity is None:
            validated_evidence_identity = validated_evidence_hash
        elif validated_evidence_hash is not None and validated_evidence_identity != validated_evidence_hash:
            raise ValueError("conflicting validated evidence identities")
        if parameter_set_id is None:
            parameter_set_id = parameter_version
        elif parameter_version is not None and parameter_set_id != parameter_version:
            raise ValueError("conflicting parameter-set identities")
        if code_version is None:
            code_version = code_revision
        elif code_revision is not None and code_version != code_revision:
            raise ValueError("conflicting code identities")
        if legacy_observations is None and legacy_observation_set is not None:
            legacy_observations = legacy_observation_set
        elif legacy_observation_set is not None and legacy_observations != legacy_observation_set:
            raise ValueError("conflicting legacy observation sets")

        decisions_from_bundle = _bundle_decisions(validated_evidence_bundle)
        decisions = _normalize_decisions(validated_decisions)
        if decisions_from_bundle is not None:
            bundled = _normalize_decisions(decisions_from_bundle)
            if decisions and decisions != bundled:
                raise ValueError("validated decisions and evidence bundle conflict")
            decisions = bundled

        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "shadow_run_id", shadow_run_id)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "information_cutoff", information_cutoff)
        object.__setattr__(self, "validated_decisions", decisions)
        object.__setattr__(self, "validated_evidence_identity", validated_evidence_identity)
        object.__setattr__(self, "legacy_observations", legacy_observations)
        object.__setattr__(self, "comparison_policy", comparison_policy)
        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "strategy_version", strategy_version)
        object.__setattr__(self, "parameter_set_id", parameter_set_id)
        object.__setattr__(self, "code_version", code_version)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "limitations", limitations)
        object.__setattr__(self, "validated_evidence_bundle", decisions if decisions_from_bundle is not None else None)
        self.__post_init__()

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unknown shadow request schema version")
        _text(self.shadow_run_id, "shadow_run_id")
        _utc(self.created_at, "created_at")
        _utc(self.information_cutoff, "information_cutoff")
        _text(self.strategy_id, "strategy_id")
        _text(self.strategy_version, "strategy_version")
        _text(self.parameter_set_id, "parameter_set_id")
        _text(self.code_version, "code_version")
        if not self.validated_decisions:
            raise ValueError("validated evidence is required")
        _require_hash(self.validated_evidence_identity, "validated_evidence_identity")
        expected = validated_evidence_identity(self.validated_decisions)
        if self.validated_evidence_identity != expected:
            raise ValueError("validated evidence identity does not match decisions")
        if not isinstance(self.comparison_policy, ShadowComparisonPolicy):
            raise TypeError("comparison_policy must be ShadowComparisonPolicy")
        if self.comparison_policy.schema_version != SCHEMA_VERSION:
            raise ValueError("unknown comparison policy schema version")
        if (self.comparison_policy.policy_id, self.comparison_policy.policy_version) not in SUPPORTED_POLICIES:
            raise ValueError("unknown comparison policy")
        if self.legacy_observations is not None and not isinstance(self.legacy_observations, LegacyObservationSet):
            raise TypeError("legacy_observations must be LegacyObservationSet or None")
        if self.legacy_observations is not None and self.legacy_observations.schema_version != SCHEMA_VERSION:
            raise ValueError("unknown legacy observation schema version")
        object.__setattr__(self, "warnings", _ordered_unique_text(self.warnings, "warnings"))
        object.__setattr__(self, "limitations", _ordered_unique_text(self.limitations, "limitations"))

    @property
    def validated_evidence_hash(self):
        return self.validated_evidence_identity

    @property
    def parameter_version(self):
        return self.parameter_set_id

    @property
    def code_revision(self):
        return self.code_version


@dataclass(frozen=True, slots=True)
class ShadowRunResult:
    """Immutable, explicitly non-authoritative output of the runner."""

    schema_version: int
    shadow_run_id: str
    created_at: datetime
    information_cutoff: datetime
    validated_evidence_identity: str
    legacy_observation_set_identity: str | None
    per_instrument_comparisons: tuple[InstrumentComparison, ...]
    comparison_summary: ShadowComparisonSummary
    unavailable_inputs: tuple[str, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    result_classification: str = field(default=RESULT_CLASSIFICATION, init=False)
    execution_authorized: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)
    runtime_effect: bool = field(default=False, init=False)
    paper_effect: bool = field(default=False, init=False)
    accounting_effect: bool = field(default=False, init=False)
    canonical_hash: str = field(default="", init=False)

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unknown shadow result schema version")
        _text(self.shadow_run_id, "shadow_run_id")
        _utc(self.created_at, "created_at")
        _utc(self.information_cutoff, "information_cutoff")
        _require_hash(self.validated_evidence_identity, "validated_evidence_identity")
        if self.legacy_observation_set_identity is not None:
            _require_hash(self.legacy_observation_set_identity, "legacy_observation_set_identity")
        if not isinstance(self.per_instrument_comparisons, tuple):
            raise TypeError("per_instrument_comparisons must be an immutable tuple")
        if any(not isinstance(item, InstrumentComparison) for item in self.per_instrument_comparisons):
            raise TypeError("per_instrument_comparisons contain invalid values")
        if not isinstance(self.comparison_summary, ShadowComparisonSummary):
            raise TypeError("comparison_summary must be ShadowComparisonSummary")
        for name in ("unavailable_inputs", "warnings", "limitations"):
            _ordered_unique_text(getattr(self, name), name)
        object.__setattr__(self, "per_instrument_comparisons", tuple(sorted(self.per_instrument_comparisons, key=lambda item: item.instrument_id)))
        object.__setattr__(self, "unavailable_inputs", _ordered_unique_text(self.unavailable_inputs, "unavailable_inputs"))
        object.__setattr__(self, "warnings", _ordered_unique_text(self.warnings, "warnings"))
        object.__setattr__(self, "limitations", _ordered_unique_text(self.limitations, "limitations"))
        if self.result_classification != RESULT_CLASSIFICATION:
            raise ValueError("result classification is fixed")
        if any(getattr(self, name) is not False for name in (
            "execution_authorized", "publication_authorized", "runtime_effect",
            "paper_effect", "accounting_effect",
        )):
            raise ValueError("shadow result safety fields are fixed false")
        object.__setattr__(self, "canonical_hash", _hash_payload(self._payload()))

    def _payload(self):
        return {
            "contract_type": "shadow_run_result",
            "schema_version": self.schema_version,
            "payload": {
                "schema_version": self.schema_version,
                "shadow_run_id": self.shadow_run_id,
                "created_at": self.created_at,
                "information_cutoff": self.information_cutoff,
                "validated_evidence_identity": self.validated_evidence_identity,
                "legacy_observation_set_identity": self.legacy_observation_set_identity,
                "per_instrument_comparisons": self.per_instrument_comparisons,
                "comparison_summary": self.comparison_summary,
                "unavailable_inputs": self.unavailable_inputs,
                "warnings": self.warnings,
                "limitations": self.limitations,
                "result_classification": self.result_classification,
                "execution_authorized": self.execution_authorized,
                "publication_authorized": self.publication_authorized,
                "runtime_effect": self.runtime_effect,
                "paper_effect": self.paper_effect,
                "accounting_effect": self.accounting_effect,
            },
        }

    def canonical_bytes(self):
        return _json_bytes(self._payload())

    @property
    def canonical_json(self):
        return self.canonical_bytes().decode("utf-8")

    @property
    def canonical_sha256(self):
        return self.canonical_hash

    @property
    def comparisons(self):
        return self.per_instrument_comparisons

    @property
    def legacy_observation_identity(self):
        return self.legacy_observation_set_identity


def _legacy_inputs(observations, cutoff):
    if observations is None:
        return (), (), ("legacy_observations: unavailable",)
    signals = []
    weights = []
    unavailable = []
    for observation in (*observations.signals, *observations.weights):
        if observation.parsing_status != "parsed":
            unavailable.append(f"legacy_observation:{observation.legacy_source_type}/{observation.source_row_id}: {observation.parsing_status}")
            continue
        future = (
            observation.observation_timestamp_utc is not None
            and observation.observation_timestamp_utc > cutoff
        ) or (
            observation.available_timestamp_utc is not None
            and observation.available_timestamp_utc > cutoff
        ) or (
            observation.observation_date is not None
            and observation.observation_date > cutoff.date()
        )
        if future:
            unavailable.append(f"legacy_observation:{observation.legacy_source_type}/{observation.source_row_id}: future_after_information_cutoff")
            continue
        if isinstance(observation, LegacySignalObservation):
            signals.append(observation)
        elif isinstance(observation, LegacyWeightObservation):
            weights.append(observation)
    return tuple(signals), tuple(weights), tuple(sorted(unavailable))


def _validate_legacy_identity(observations):
    if observations is None:
        return None
    identities = set()
    signal_instruments = {}
    weight_instruments = {}
    for observation in (*observations.signals, *observations.weights, *observations.projections):
        identity = (observation.legacy_source_type, observation.source_row_id)
        if identity in identities:
            raise ValueError("conflicting duplicate legacy observation identity")
        identities.add(identity)
    for observation in observations.signals:
        prior = signal_instruments.get(observation.instrument_id)
        if prior is not None and prior != observation:
            raise ValueError("conflicting legacy signal observations for one instrument")
        signal_instruments[observation.instrument_id] = observation
    for observation in observations.weights:
        prior = weight_instruments.get(observation.instrument_id)
        if prior is not None and prior != observation:
            raise ValueError("conflicting legacy weight observations for one instrument")
        weight_instruments[observation.instrument_id] = observation
    return observations.canonical_hash


def run_shadow_comparison(request):
    """Run one deterministic, in-memory, non-authoritative shadow comparison."""
    if not isinstance(request, ShadowRunRequest):
        raise TypeError("request must be ShadowRunRequest")
    # Request construction validates the decision evidence before any legacy
    # evidence is considered, so invalid validated evidence cannot fall back.
    legacy_identity = _validate_legacy_identity(request.legacy_observations)
    signals, weights, unavailable = _legacy_inputs(request.legacy_observations, request.information_cutoff)
    if any(
        decision.decision_timestamp_utc > request.information_cutoff
        or decision.information_cutoff_utc > request.information_cutoff
        for decision in request.validated_decisions
    ):
        raise ValueError("validated evidence occurs after information cutoff")
    comparisons, summary = compare_shadow_observations(
        validated_decisions=request.validated_decisions,
        legacy_signals=signals,
        legacy_weights=weights,
        policy=request.comparison_policy,
    )
    result = ShadowRunResult(
        schema_version=SCHEMA_VERSION,
        shadow_run_id=request.shadow_run_id,
        created_at=request.created_at,
        information_cutoff=request.information_cutoff,
        validated_evidence_identity=request.validated_evidence_identity,
        legacy_observation_set_identity=legacy_identity,
        per_instrument_comparisons=comparisons,
        comparison_summary=summary,
        unavailable_inputs=unavailable,
        warnings=request.warnings,
        limitations=request.limitations,
    )
    return result


__all__ = [
    "RESULT_CLASSIFICATION",
    "SCHEMA_VERSION",
    "ShadowRunRequest",
    "ShadowRunResult",
    "canonical_sha256",
    "run_shadow_comparison",
    "validated_evidence_identity",
]
