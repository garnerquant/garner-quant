"""Pure, non-authoritative comparison of validated decisions and legacy observations."""

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from datetime import datetime, timezone
import hashlib
import json

from research.legacy_observations import LegacySignalObservation, LegacyWeightObservation
from strategy.contract import DecisionAction, DecisionStatus, StrategyDecision


OUTCOMES = frozenset({"agree", "differ", "unavailable", "incomparable", "excluded", "legacy_only", "validated_only", "timing_mismatch", "unit_mismatch", "currency_mismatch", "methodology_mismatch"})


def _text(value, field):
    if not isinstance(value, str) or not value.strip(): raise ValueError(f"{field} must be nonblank")
    return value


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value): raise ValueError(f"{field} must be timezone-aware UTC")


def _canonical(value):
    if value is None or isinstance(value, (str, int, bool)): return value
    if isinstance(value, Decimal): return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, datetime): return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, tuple): return [_canonical(x) for x in value]
    if is_dataclass(value): return {f.name: _canonical(getattr(value, f.name)) for f in fields(value)}
    raise TypeError(f"unsupported comparison value: {type(value).__name__}")


def _hash(value): return hashlib.sha256(json.dumps(_canonical(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ShadowComparisonPolicy:
    schema_version: int
    policy_id: str
    policy_version: str
    base_currency: str
    validated_methodology: str
    legacy_methodology: str

    def __post_init__(self):
        if not isinstance(self.schema_version, int) or self.schema_version <= 0: raise ValueError("schema_version must be positive")
        for field in ("policy_id", "policy_version", "validated_methodology", "legacy_methodology"): _text(getattr(self, field), field)
        if not isinstance(self.base_currency, str) or self.base_currency != self.base_currency.upper() or len(self.base_currency) != 3: raise ValueError("base_currency must be uppercase ISO-style text")


@dataclass(frozen=True, slots=True)
class ShadowDifference:
    dimension: str
    outcome: str
    explanation: str

    def __post_init__(self):
        _text(self.dimension, "dimension"); _text(self.explanation, "explanation")
        if self.outcome not in OUTCOMES: raise ValueError("unknown comparison outcome")


@dataclass(frozen=True, slots=True)
class InstrumentComparison:
    instrument_id: str
    differences: tuple[ShadowDifference, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.instrument_id, "instrument_id")
        if any(not isinstance(x, ShadowDifference) for x in self.differences): raise TypeError("differences must contain ShadowDifference values")

    @property
    def canonical_hash(self): return _hash(self)


@dataclass(frozen=True, slots=True)
class ShadowComparisonSummary:
    compared_count: int
    outcome_counts: tuple[tuple[str, int], ...]
    validated_only: tuple[str, ...]
    legacy_only: tuple[str, ...]
    methodology_warnings: tuple[str, ...]
    result_classification: str = "shadow_observation_unverified"

    def __post_init__(self):
        if not isinstance(self.compared_count, int) or self.compared_count < 0: raise ValueError("compared_count must be nonnegative integer")
        if self.result_classification != "shadow_observation_unverified": raise ValueError("shadow result classification is fixed")

    @property
    def canonical_hash(self): return _hash(self)


def _legacy_direction(signal):
    if signal is None: return None
    return "positive" if signal > 0 else "negative" if signal < 0 else "neutral"


def _validated_direction(action):
    if action in {DecisionAction.BUY, DecisionAction.HOLD}: return "positive"
    if action in {DecisionAction.SELL, DecisionAction.EXIT}: return "negative"
    return "neutral"


def _weight(value, unit):
    if value is None or unit is None: return None
    if unit == "fraction": return value
    if unit == "percent": return value / Decimal("100")
    return None


def compare_shadow_observations(*, validated_decisions: tuple[StrategyDecision, ...], legacy_signals: tuple[LegacySignalObservation, ...], legacy_weights: tuple[LegacyWeightObservation, ...] = (), policy: ShadowComparisonPolicy) -> tuple[tuple[InstrumentComparison, ...], ShadowComparisonSummary]:
    if not isinstance(policy, ShadowComparisonPolicy): raise TypeError("policy must be ShadowComparisonPolicy")
    if any(not isinstance(x, StrategyDecision) for x in validated_decisions): raise TypeError("validated_decisions must contain StrategyDecision values")
    if any(not isinstance(x, LegacySignalObservation) for x in legacy_signals): raise TypeError("legacy_signals must contain LegacySignalObservation values")
    if any(not isinstance(x, LegacyWeightObservation) for x in legacy_weights): raise TypeError("legacy_weights must contain LegacyWeightObservation values")
    validated = {x.instrument_id: x for x in validated_decisions}
    legacy = {x.instrument_id: x for x in legacy_signals}
    weights = {x.instrument_id: x for x in legacy_weights}
    results = []
    counts = {}
    warnings = []
    for instrument in sorted(set(validated) | set(legacy)):
        if instrument not in validated:
            result = InstrumentComparison(instrument, (ShadowDifference("instrument_eligibility", "legacy_only", "legacy observation has no matching validated decision"),))
        elif instrument not in legacy:
            result = InstrumentComparison(instrument, (ShadowDifference("instrument_eligibility", "validated_only", "validated decision has no matching legacy observation"),))
        else:
            decision, signal = validated[instrument], legacy[instrument]
            differences = []
            direction = _legacy_direction(signal.signal_value)
            if direction is None: differences.append(ShadowDifference("signal_direction", "unavailable", "legacy signal value is missing"))
            else: differences.append(ShadowDifference("signal_direction", "agree" if direction == _validated_direction(decision.decision_action) else "differ", "direction compared without treating agreement as validation"))
            legacy_status = "eligible" if (signal.status or "").lower() in {"buy", "hold", "sell", "eligible"} else "rejected" if signal.status else None
            if legacy_status is None: differences.append(ShadowDifference("decision_status", "unavailable", "legacy status is missing or ambiguous"))
            else: differences.append(ShadowDifference("decision_status", "agree" if legacy_status == decision.decision_status.value else "differ", "explicit status values compared"))
            weight = _weight(weights[instrument].weight, weights[instrument].weight_unit) if instrument in weights else _weight(signal.weight, signal.weight_unit)
            if decision.target_weight is None or weight is None: differences.append(ShadowDifference("target_weight", "unavailable", "weight or declared unit is missing"))
            else: differences.append(ShadowDifference("target_weight", "agree" if decision.target_weight == weight else "differ", "weights compared after explicit fraction/percent interpretation"))
            if signal.observation_timestamp_utc is None: differences.append(ShadowDifference("timing", "unavailable", "legacy observation timestamp is unavailable"))
            elif signal.observation_timestamp_utc == decision.decision_timestamp_utc: differences.append(ShadowDifference("timing", "agree", "timestamps are equal; this does not establish safe execution"))
            else: differences.append(ShadowDifference("timing", "timing_mismatch", "explicit observation and decision timestamps differ"))
            if signal.currency is None or signal.price_unit is None: differences.append(ShadowDifference("currency_unit", "unavailable", "legacy currency or price unit is unavailable"))
            elif signal.currency != decision.currency: differences.append(ShadowDifference("currency", "currency_mismatch", "notionals cannot be compared across currencies without eligible FX"))
            elif signal.price_unit != decision.price_unit: differences.append(ShadowDifference("price_unit", "unit_mismatch", "price units are not equivalent"))
            else: differences.append(ShadowDifference("currency_unit", "agree", "explicit currency and price unit match"))
            warning = f"validated methodology {policy.validated_methodology} compared with unverified legacy methodology {signal.methodology_classification}"
            differences.append(ShadowDifference("methodology", "methodology_mismatch", warning)); warnings.append(warning)
            result = InstrumentComparison(instrument, tuple(differences), (warning,))
        results.append(result)
        for difference in result.differences: counts[difference.outcome] = counts.get(difference.outcome, 0) + 1
    summary = ShadowComparisonSummary(sum(1 for x in results if x.instrument_id in validated and x.instrument_id in legacy), tuple(sorted(counts.items())), tuple(sorted(set(validated) - set(legacy))), tuple(sorted(set(legacy) - set(validated))), tuple(sorted(set(warnings))))
    return tuple(results), summary
