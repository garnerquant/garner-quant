"""Strict, side-effect-free decoder for explicitly supplied shadow input JSON."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
import unicodedata

from research.legacy_observations import (
    LegacyObservationSet,
    LegacyPortfolioProjection,
    LegacySignalObservation,
    LegacyWeightObservation,
)
from research.shadow_comparison import ShadowComparisonPolicy
from research import shadow_runner as _shadow_runner
from strategy.contract import (
    DataQualityStatus,
    DecisionAction,
    DecisionStatus,
    StrategyDecision,
)


SCHEMA_VERSION = 1
REQUEST_TYPE = "manual_shadow_input_v1"
MAX_INPUT_BYTES = 262144
MAX_DECISIONS = 100
MAX_LEGACY_OBSERVATIONS = 200
MAX_STRING_LENGTH = 4096
MAX_WARNINGS = 32
MAX_LIMITATIONS = 32
MAX_COLLECTION_LENGTH = 256
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_NEGATIVE_ZERO = re.compile(r"^-0(?:\.0+)?$")
_FORBIDDEN_KEYS = frozenset({
    "result_classification", "execution_authorized", "publication_authorized",
    "runtime_effect", "paper_effect", "accounting_effect",
})


class ShadowInputError(ValueError):
    """Raised when an explicit manual shadow-input document is invalid."""


@dataclass(frozen=True, slots=True)
class DecodedShadowInput:
    """Immutable decoded input and its raw and canonical content identities."""

    schema_version: int
    request_type: str
    request: _shadow_runner.ShadowRunRequest
    raw_input_sha256: str
    canonical_input_sha256: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION or self.request_type != REQUEST_TYPE:
            raise ShadowInputError("unknown manual shadow input version")
        if not isinstance(self.request, _shadow_runner.ShadowRunRequest):
            raise TypeError("request must be ShadowRunRequest")
        for value in (self.raw_input_sha256, self.canonical_input_sha256):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ShadowInputError("input hashes must be lowercase SHA-256 digests")
        if self.warnings != self.request.warnings or self.limitations != self.request.limitations:
            raise ShadowInputError("decoded warnings and limitations must match request")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ShadowInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_float(_value):
    raise ShadowInputError("JSON floats are not allowed")


def _reject_constant(value):
    raise ShadowInputError(f"JSON constant is not allowed: {value}")


def _raw_bytes(raw):
    if isinstance(raw, str):
        if raw.startswith("\ufeff"):
            raise ShadowInputError("UTF-8 BOM is not allowed")
        encoded = raw.encode("utf-8", "strict")
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise TypeError("raw input must be text or UTF-8 bytes")
    if len(encoded) > MAX_INPUT_BYTES:
        raise ShadowInputError("input exceeds maximum byte length")
    if encoded.startswith(b"\xef\xbb\xbf"):
        raise ShadowInputError("UTF-8 BOM is not allowed")
    try:
        return encoded, encoded.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ShadowInputError("input is not valid UTF-8") from exc


def raw_input_sha256(raw):
    """Return the lowercase SHA-256 of caller-supplied text or UTF-8 bytes."""
    encoded, _ = _raw_bytes(raw)
    return hashlib.sha256(encoded).hexdigest()


def _object(value, name, expected):
    if not isinstance(value, dict):
        raise ShadowInputError(f"{name} must be an object")
    actual = set(value)
    expected = set(expected)
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ShadowInputError(f"{name} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ShadowInputError(f"{name} is missing fields: {sorted(missing)}")
    return value


def _collection(value, name, maximum=MAX_COLLECTION_LENGTH):
    if not isinstance(value, list):
        raise ShadowInputError(f"{name} must be an array")
    if len(value) > maximum:
        raise ShadowInputError(f"{name} exceeds maximum collection length")
    return value


def _text(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or not value.strip():
        raise ShadowInputError(f"{name} must be nonblank text")
    if len(value) > MAX_STRING_LENGTH:
        raise ShadowInputError(f"{name} exceeds maximum string length")
    if any(marker in value for marker in ("://", "\\", "/", "$(", "`", ";", "\x00")):
        raise ShadowInputError(f"{name} contains a path, URL, or shell syntax")
    return unicodedata.normalize("NFC", value)


def _hash(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    value = _text(value, name)
    if not _SHA256.fullmatch(value):
        raise ShadowInputError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _integer(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ShadowInputError(f"{name} must be an integer")
    if positive and value <= 0:
        raise ShadowInputError(f"{name} must be positive")
    return value


def _timestamp(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    value = _text(value, name)
    if not _TIMESTAMP.fullmatch(value):
        raise ShadowInputError(f"{name} must be a canonical UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ShadowInputError(f"{name} is not a valid timestamp") from exc


def _date(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    value = _text(value, name)
    if not _DATE.fullmatch(value):
        raise ShadowInputError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ShadowInputError(f"{name} is not a valid date") from exc


def _decimal(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ShadowInputError(f"{name} must be a canonical Decimal string")
    if len(value) > MAX_STRING_LENGTH or "e" in value.lower():
        raise ShadowInputError(f"{name} must not use scientific notation")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ShadowInputError(f"{name} is not a Decimal") from exc
    if not parsed.is_finite():
        raise ShadowInputError(f"{name} must be finite")
    canonical = "0" if parsed == 0 else format(parsed.normalize(), "f")
    if value != canonical and not (parsed == 0 and _NEGATIVE_ZERO.fullmatch(value)):
        raise ShadowInputError(f"{name} is not canonical")
    return Decimal(canonical)


def _enum(enum_type, value, name):
    value = _text(value, name)
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ShadowInputError(f"{name} is not a supported enum value") from exc


def _texts(value, name, maximum):
    values = tuple(_text(item, name) for item in _collection(value, name, maximum))
    if len(set(values)) != len(values):
        raise ShadowInputError(f"{name} must not contain duplicates")
    return values


def _provenance(value):
    items = []
    for index, pair in enumerate(_collection(value, "raw_field_provenance", MAX_COLLECTION_LENGTH)):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ShadowInputError(f"raw_field_provenance[{index}] must contain two strings")
        items.append((_text(pair[0], "raw_field_provenance key"), _text(pair[1], "raw_field_provenance value")))
    return tuple(items)


def _decision(value):
    names = (
        "decision_id", "strategy_id", "strategy_version", "instrument_id",
        "decision_timestamp_utc", "information_cutoff_utc", "eligible_execution_timestamp_utc",
        "decision_action", "decision_status", "signal_value", "target_weight", "currency",
        "price_unit", "quality_status", "reason_codes", "dataset_version", "universe_version",
        "parameter_version", "code_revision",
    )
    value = _object(value, "validated_decision", names)
    return StrategyDecision(
        _text(value["decision_id"], "decision_id"), _text(value["strategy_id"], "strategy_id"),
        _text(value["strategy_version"], "strategy_version"), _text(value["instrument_id"], "instrument_id"),
        _timestamp(value["decision_timestamp_utc"], "decision_timestamp_utc"),
        _timestamp(value["information_cutoff_utc"], "information_cutoff_utc"),
        _timestamp(value["eligible_execution_timestamp_utc"], "eligible_execution_timestamp_utc"),
        _enum(DecisionAction, value["decision_action"], "decision_action"),
        _enum(DecisionStatus, value["decision_status"], "decision_status"),
        _decimal(value["signal_value"], "signal_value", nullable=True),
        _decimal(value["target_weight"], "target_weight", nullable=True),
        _currency(value["currency"]), _text(value["price_unit"], "price_unit"),
        _enum(DataQualityStatus, value["quality_status"], "quality_status"),
        _texts(value["reason_codes"], "reason_codes", MAX_COLLECTION_LENGTH),
        _text(value["dataset_version"], "dataset_version"), _text(value["universe_version"], "universe_version"),
        _text(value["parameter_version"], "parameter_version"), _text(value["code_revision"], "code_revision"),
    )


def _currency(value, *, nullable=False):
    if value is None and nullable:
        return None
    value = _text(value, "currency")
    if value != value.upper() or len(value) != 3:
        raise ShadowInputError("currency must be uppercase ISO-style text")
    return value


def _legacy_common(value, names, kind):
    value = _object(value, kind, names)
    return value


def _signal(value):
    names = (
        "schema_version", "legacy_source_type", "source_artifact_hash", "source_row_id", "instrument_id",
        "observation_date", "observation_timestamp_utc", "available_timestamp_utc", "signal_value",
        "weight", "weight_unit", "status", "currency", "price_unit", "methodology_classification",
        "parsing_status", "limitations", "raw_field_provenance",
    )
    value = _legacy_common(value, names, "legacy_signal")
    return LegacySignalObservation(
        _integer(value["schema_version"], "legacy signal schema_version", positive=True),
        _text(value["legacy_source_type"], "legacy_source_type"), _hash(value["source_artifact_hash"], "source_artifact_hash"),
        _text(value["source_row_id"], "source_row_id"), _text(value["instrument_id"], "instrument_id"),
        _date(value["observation_date"], "observation_date", nullable=True),
        _timestamp(value["observation_timestamp_utc"], "observation_timestamp_utc", nullable=True),
        _timestamp(value["available_timestamp_utc"], "available_timestamp_utc", nullable=True),
        _decimal(value["signal_value"], "signal_value", nullable=True), _decimal(value["weight"], "weight", nullable=True),
        _text(value["weight_unit"], "weight_unit", nullable=True), _text(value["status"], "status", nullable=True),
        _currency(value["currency"], nullable=True), _text(value["price_unit"], "price_unit", nullable=True),
        _text(value["methodology_classification"], "methodology_classification"), _text(value["parsing_status"], "parsing_status"),
        _texts(value["limitations"], "legacy limitations", MAX_LIMITATIONS), _provenance(value["raw_field_provenance"]),
    )


def _weight(value):
    names = (
        "schema_version", "legacy_source_type", "source_artifact_hash", "source_row_id", "instrument_id",
        "observation_date", "observation_timestamp_utc", "available_timestamp_utc", "weight", "weight_unit",
        "notional", "quantity", "price", "currency", "price_unit", "methodology_classification",
        "parsing_status", "limitations", "raw_field_provenance",
    )
    value = _legacy_common(value, names, "legacy_weight")
    return LegacyWeightObservation(
        _integer(value["schema_version"], "legacy weight schema_version", positive=True),
        _text(value["legacy_source_type"], "legacy_source_type"), _hash(value["source_artifact_hash"], "source_artifact_hash"),
        _text(value["source_row_id"], "source_row_id"), _text(value["instrument_id"], "instrument_id"),
        _date(value["observation_date"], "observation_date", nullable=True),
        _timestamp(value["observation_timestamp_utc"], "observation_timestamp_utc", nullable=True),
        _timestamp(value["available_timestamp_utc"], "available_timestamp_utc", nullable=True),
        _decimal(value["weight"], "weight", nullable=True), _text(value["weight_unit"], "weight_unit", nullable=True),
        _decimal(value["notional"], "notional", nullable=True), _decimal(value["quantity"], "quantity", nullable=True),
        _decimal(value["price"], "price", nullable=True), _currency(value["currency"], nullable=True),
        _text(value["price_unit"], "price_unit", nullable=True), _text(value["methodology_classification"], "methodology_classification"),
        _text(value["parsing_status"], "parsing_status"), _texts(value["limitations"], "legacy limitations", MAX_LIMITATIONS),
        _provenance(value["raw_field_provenance"]),
    )


def _projection(value):
    names = (
        "schema_version", "legacy_source_type", "source_artifact_hash", "source_row_id", "observation_date",
        "portfolio_value", "cash", "realised_pnl", "unrealised_pnl", "benchmark_return", "currency",
        "methodology_classification", "parsing_status", "limitations", "raw_field_provenance",
    )
    value = _legacy_common(value, names, "legacy_projection")
    return LegacyPortfolioProjection(
        _integer(value["schema_version"], "legacy projection schema_version", positive=True),
        _text(value["legacy_source_type"], "legacy_source_type"), _hash(value["source_artifact_hash"], "source_artifact_hash"),
        _text(value["source_row_id"], "source_row_id"), _date(value["observation_date"], "observation_date", nullable=True),
        _decimal(value["portfolio_value"], "portfolio_value", nullable=True), _decimal(value["cash"], "cash", nullable=True),
        _decimal(value["realised_pnl"], "realised_pnl", nullable=True), _decimal(value["unrealised_pnl"], "unrealised_pnl", nullable=True),
        _decimal(value["benchmark_return"], "benchmark_return", nullable=True), _currency(value["currency"], nullable=True),
        _text(value["methodology_classification"], "methodology_classification"), _text(value["parsing_status"], "parsing_status"),
        _texts(value["limitations"], "legacy limitations", MAX_LIMITATIONS), _provenance(value["raw_field_provenance"]),
    )


def _legacy(value, identity, cutoff):
    if value is None:
        if identity is not None:
            raise ShadowInputError("legacy observation identity requires observations")
        return None
    names = ("schema_version", "signals", "weights", "projections", "methodology_classification", "limitations")
    value = _object(value, "legacy_observations", names)
    signals = tuple(_signal(item) for item in _collection(value["signals"], "legacy signals", MAX_LEGACY_OBSERVATIONS))
    weights = tuple(_weight(item) for item in _collection(value["weights"], "legacy weights", MAX_LEGACY_OBSERVATIONS))
    projections = tuple(_projection(item) for item in _collection(value["projections"], "legacy projections", MAX_LEGACY_OBSERVATIONS))
    if len(signals) + len(weights) + len(projections) > MAX_LEGACY_OBSERVATIONS:
        raise ShadowInputError("legacy observations exceed maximum count")
    identities = [(item.legacy_source_type, item.source_row_id) for item in (*signals, *weights, *projections)]
    if len(identities) != len(set(identities)):
        raise ShadowInputError("duplicate legacy observation identity")
    if len({item.instrument_id for item in signals}) != len(signals) or len({item.instrument_id for item in weights}) != len(weights):
        raise ShadowInputError("conflicting legacy observations for one instrument")
    for item in (*signals, *weights):
        if item.parsing_status != "parsed":
            raise ShadowInputError("legacy observations must have parsed status")
        if ((item.observation_timestamp_utc and item.observation_timestamp_utc > cutoff) or
                (item.available_timestamp_utc and item.available_timestamp_utc > cutoff) or
                (item.observation_date and item.observation_date > cutoff.date())):
            raise ShadowInputError("legacy evidence occurs after information cutoff")
    result = LegacyObservationSet(
        _integer(value["schema_version"], "legacy schema_version", positive=True), signals, weights, projections,
        _text(value["methodology_classification"], "methodology_classification"),
        _texts(value["limitations"], "legacy set limitations", MAX_LIMITATIONS),
    )
    if identity != result.canonical_hash:
        raise ShadowInputError("legacy observation identity does not match observations")
    return result


def _policy(value):
    names = ("schema_version", "policy_id", "policy_version", "base_currency", "validated_methodology", "legacy_methodology")
    value = _object(value, "comparison_policy", names)
    return ShadowComparisonPolicy(
        _integer(value["schema_version"], "policy schema_version", positive=True), _text(value["policy_id"], "policy_id"),
        _text(value["policy_version"], "policy_version"), _currency(value["base_currency"]),
        _text(value["validated_methodology"], "validated_methodology"), _text(value["legacy_methodology"], "legacy_methodology"),
    )


def _forbidden(value):
    if isinstance(value, dict):
        overlap = set(value) & _FORBIDDEN_KEYS
        if overlap:
            raise ShadowInputError(f"fixed safety fields are forbidden: {sorted(overlap)}")
        for item in value.values():
            _forbidden(item)
    elif isinstance(value, list):
        for item in value:
            _forbidden(item)


def _canonical(value):
    if isinstance(value, Enum):
        return _canonical(value.value)
    if value is None or isinstance(value, (str, int, bool)):
        return unicodedata.normalize("NFC", value) if isinstance(value, str) else value
    if isinstance(value, Decimal):
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    raise TypeError(f"unsupported canonical input value: {type(value).__name__}")


def _decision_payload(decision):
    return _canonical(decision)


def _legacy_payload(observations):
    if observations is None:
        return None
    return {
        "schema_version": observations.schema_version,
        "signals": [_canonical(item) for item in sorted(observations.signals, key=lambda item: (item.instrument_id, item.source_row_id))],
        "weights": [_canonical(item) for item in sorted(observations.weights, key=lambda item: (item.instrument_id, item.source_row_id))],
        "projections": [_canonical(item) for item in sorted(observations.projections, key=lambda item: item.source_row_id)],
        "methodology_classification": observations.methodology_classification,
        "limitations": sorted(observations.limitations),
    }


def to_canonical_input_payload(decoded):
    """Return the deterministic semantic payload of a decoded manual input."""
    if not isinstance(decoded, DecodedShadowInput):
        raise TypeError("decoded must be DecodedShadowInput")
    request = decoded.request
    policy = request.comparison_policy
    return {
        "schema_version": SCHEMA_VERSION,
        "request_type": REQUEST_TYPE,
        "shadow_run_id": request.shadow_run_id,
        "created_at": _canonical(request.created_at),
        "information_cutoff": _canonical(request.information_cutoff),
        "strategy_id": request.strategy_id,
        "strategy_version": request.strategy_version,
        "parameter_set_id": request.parameter_set_id,
        "code_version": request.code_version,
        "validated_evidence_identity": request.validated_evidence_identity,
        "validated_decisions": [_decision_payload(item) for item in request.validated_decisions],
        "legacy_observation_set_identity": request.legacy_observations.canonical_hash if request.legacy_observations else None,
        "legacy_observations": _legacy_payload(request.legacy_observations),
        "comparison_policy": _canonical(policy),
        "warnings": list(request.warnings),
        "limitations": list(request.limitations),
    }


def to_canonical_input_bytes(decoded):
    """Return compact UTF-8 canonical bytes for a decoded manual input."""
    return json.dumps(to_canonical_input_payload(decoded), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_input_sha256(decoded):
    """Return the lowercase SHA-256 of the semantic canonical input bytes."""
    return hashlib.sha256(to_canonical_input_bytes(decoded)).hexdigest()


def decode_shadow_input(raw):
    """Decode one supplied JSON document into a validated immutable request.

    This function reads no files, invokes no runner, and has no side effects.
    """
    encoded, text = _raw_bytes(raw)
    try:
        document = json.loads(text, object_pairs_hook=_pairs, parse_float=_reject_float, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ShadowInputError) as exc:
        if isinstance(exc, ShadowInputError):
            raise
        raise ShadowInputError("input is not valid JSON") from exc
    names = (
        "schema_version", "request_type", "shadow_run_id", "created_at", "information_cutoff", "strategy_id",
        "strategy_version", "parameter_set_id", "code_version", "validated_evidence_identity", "validated_decisions",
        "legacy_observation_set_identity", "legacy_observations", "comparison_policy", "warnings", "limitations",
    )
    document = _object(document, "manual shadow input", names)
    _forbidden(document)
    if _integer(document["schema_version"], "schema_version", positive=True) != SCHEMA_VERSION:
        raise ShadowInputError("unknown manual shadow input schema version")
    if _text(document["request_type"], "request_type") != REQUEST_TYPE:
        raise ShadowInputError("unknown manual shadow input request type")
    created_at = _timestamp(document["created_at"], "created_at")
    cutoff = _timestamp(document["information_cutoff"], "information_cutoff")
    decisions = tuple(_decision(item) for item in _collection(document["validated_decisions"], "validated_decisions", MAX_DECISIONS))
    if not decisions:
        raise ShadowInputError("validated_decisions must not be empty")
    if len({item.decision_id for item in decisions}) != len(decisions) or len({item.instrument_id for item in decisions}) != len(decisions):
        raise ShadowInputError("duplicate or conflicting validated decision identity")
    if any(item.decision_timestamp_utc > cutoff or item.information_cutoff_utc > cutoff for item in decisions):
        raise ShadowInputError("validated evidence occurs after information cutoff")
    strategy_id = _text(document["strategy_id"], "strategy_id")
    strategy_version = _text(document["strategy_version"], "strategy_version")
    parameter_set_id = _text(document["parameter_set_id"], "parameter_set_id")
    code_version = _text(document["code_version"], "code_version")
    if any((item.strategy_id, item.strategy_version, item.parameter_version, item.code_revision) != (strategy_id, strategy_version, parameter_set_id, code_version) for item in decisions):
        raise ShadowInputError("request identity fields must match every validated decision")
    evidence_identity = _hash(document["validated_evidence_identity"], "validated_evidence_identity")
    if evidence_identity != _shadow_runner.validated_evidence_identity(decisions):
        raise ShadowInputError("validated evidence identity does not match decisions")
    legacy_identity = _hash(document["legacy_observation_set_identity"], "legacy_observation_set_identity", nullable=True)
    observations = _legacy(document["legacy_observations"], legacy_identity, cutoff)
    warnings = _texts(document["warnings"], "warnings", MAX_WARNINGS)
    limitations = _texts(document["limitations"], "limitations", MAX_LIMITATIONS)
    try:
        request = _shadow_runner.ShadowRunRequest(
            SCHEMA_VERSION, _text(document["shadow_run_id"], "shadow_run_id"), created_at, cutoff, decisions,
            evidence_identity, observations, _policy(document["comparison_policy"]), strategy_id, strategy_version,
            parameter_set_id, code_version, warnings, limitations,
        )
    except (TypeError, ValueError) as exc:
        raise ShadowInputError("manual shadow input violates existing contract") from exc
    provisional = DecodedShadowInput(SCHEMA_VERSION, REQUEST_TYPE, request, hashlib.sha256(encoded).hexdigest(), "0" * 64, warnings, limitations)
    return DecodedShadowInput(SCHEMA_VERSION, REQUEST_TYPE, request, provisional.raw_input_sha256, canonical_input_sha256(provisional), warnings, limitations)


__all__ = [
    "DecodedShadowInput", "MAX_COLLECTION_LENGTH", "MAX_DECISIONS", "MAX_INPUT_BYTES", "MAX_LEGACY_OBSERVATIONS",
    "MAX_LIMITATIONS", "MAX_STRING_LENGTH", "MAX_WARNINGS", "REQUEST_TYPE", "SCHEMA_VERSION", "ShadowInputError",
    "canonical_input_sha256", "decode_shadow_input", "raw_input_sha256", "to_canonical_input_bytes", "to_canonical_input_payload",
]
