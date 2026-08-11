"""Deterministic, caller-supplied research-run provenance."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import unicodedata


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamps must be timezone-aware UTC")


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _value(value):
    if isinstance(value, Decimal):
        if not value.is_finite(): raise ValueError("non-finite Decimal")
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, datetime):
        _utc(value); return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, str): return unicodedata.normalize("NFC", value)
    if isinstance(value, tuple): return [_value(v) for v in value]
    if isinstance(value, dict): return {unicodedata.normalize("NFC", k): _value(value[k]) for k in sorted(value)}
    if value is None or isinstance(value, (bool, int)): return value
    raise TypeError(f"unsupported manifest value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class ResearchRunManifest:
    schema_version: int
    run_id: str
    created_at: datetime
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    universe_id: str
    universe_version: str
    information_cutoff: datetime
    datasets: tuple[tuple[str, str, str], ...]
    code_revision: str
    instrument_metadata_version: str
    price_basis: str
    benchmark_instrument: str
    benchmark_currency_policy: str
    execution_model_version: str
    cost_model_version: str
    result_classification: str = "exploratory_unverified"
    warnings: tuple[str, ...] = ()
    fx_dataset: tuple[str, str] | None = None
    fundamental_snapshot: tuple[str, str] | None = None
    corporate_action_dataset: tuple[str, str] | None = None
    random_seed: int | None = None
    parent_run_id: str | None = None

    def __post_init__(self):
        if self.schema_version <= 0: raise ValueError("schema_version must be positive")
        _utc(self.created_at); _utc(self.information_cutoff)
        for field in ("run_id", "strategy_id", "strategy_version", "parameter_set_id", "universe_id", "universe_version", "code_revision", "instrument_metadata_version", "price_basis", "benchmark_instrument", "benchmark_currency_policy", "execution_model_version", "cost_model_version"):
            _text(getattr(self, field), field)
        if self.result_classification != "exploratory_unverified":
            raise ValueError("this manifest only permits exploratory_unverified classification")
        if not all(len(item) == 3 and all(isinstance(v, str) and v for v in item) for item in self.datasets):
            raise ValueError("datasets require name, version and content hash")

    def payload(self):
        return _value({field: getattr(self, field) for field in self.__dataclass_fields__})


def manifest_bytes(manifest: ResearchRunManifest) -> bytes:
    envelope = {"contract_type": "research_run_manifest", "schema_version": 1, "payload": manifest.payload()}
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_sha256(manifest: ResearchRunManifest) -> str:
    return hashlib.sha256(manifest_bytes(manifest)).hexdigest()
