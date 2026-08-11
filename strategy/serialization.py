"""Pure canonical JSON and integrity identifiers for strategy contracts."""

import hashlib
import json
import unicodedata
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from strategy.contract import NormalizedMarketBar, StrategyDecision


SCHEMA_VERSION = 1


def _string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("Decimal values must be finite")
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware UTC")
        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("datetime values must represent UTC")
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, str):
        return _string(value)
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError("float values are not supported in canonical JSON")
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON mappings require string keys")
            normalized_key = _string(key)
            if normalized_key in normalized:
                raise ValueError("canonical JSON mapping keys must be unique after normalization")
            normalized[normalized_key] = _canonical_value(item)
        return normalized
    if is_dataclass(value):
        raise TypeError("nested dataclasses are not supported in canonical payloads")
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _contract_payload(contract: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(contract, NormalizedMarketBar):
        contract_type = "normalized_market_bar"
    elif isinstance(contract, StrategyDecision):
        contract_type = "strategy_decision"
    else:
        raise TypeError("canonical serialization supports only NormalizedMarketBar and StrategyDecision")
    payload = {
        field.name: _canonical_value(getattr(contract, field.name))
        for field in fields(contract)
    }
    return contract_type, payload


def to_canonical_payload(contract: Any) -> dict[str, Any]:
    contract_type, payload = _contract_payload(contract)
    return {
        "contract_type": contract_type,
        "schema_version": SCHEMA_VERSION,
        "payload": payload,
    }


def to_canonical_json_bytes(contract: Any) -> bytes:
    return json.dumps(
        to_canonical_payload(contract),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(contract: Any) -> str:
    return hashlib.sha256(to_canonical_json_bytes(contract)).hexdigest()
