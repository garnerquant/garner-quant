from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any


class DecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    MONITOR_ONLY = "MONITOR_ONLY"


def utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return result.astimezone(timezone.utc)


def decimal_value(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite float cannot be serialized")
    return value


@dataclass(frozen=True)
class OrderProposal:
    proposal_id: str
    strategy_id: str
    signal_id: str
    symbol: str
    market: str
    side: str
    quantity: Decimal
    order_type: str
    limit_price: Decimal | None
    stop_price: Decimal | None
    time_in_force: str
    strategy_timestamp: datetime
    source_bar_timestamp: datetime
    expected_execution_currency: str
    reason: str
    correlation_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(cls, **values) -> "OrderProposal":
        data = dict(values)
        data["quantity"] = decimal_value(data.get("quantity"), "quantity")
        for name in ("limit_price", "stop_price"):
            if data.get(name) is not None:
                data[name] = decimal_value(data[name], name)
        for name in ("strategy_timestamp", "source_bar_timestamp", "created_at"):
            if name in data and data[name] is not None:
                data[name] = utc_datetime(data[name], name)
        return cls(**data)

    def canonical_payload(self) -> dict[str, Any]:
        return json_value(asdict(self))

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RiskContext:
    now: datetime
    runtime_mode: str
    trading_enabled: bool
    runtime_healthy: bool
    scheduler_healthy: bool
    adapter_ready: bool
    market_session_valid: bool
    source_bar_complete: bool
    reference_price: Decimal | None
    reference_price_timestamp: datetime | None
    fx_rate_to_base: Decimal | None
    fx_timestamp: datetime | None
    accounting_active: bool
    accounting_verified: bool
    accounting_generation_id: str | None
    accounting_base_currency: str | None
    accounting_reconciled: bool
    cash_base: Decimal | None
    portfolio_equity_base: Decimal | None
    positions_base: dict[str, Decimal] | None
    position_quantities: dict[str, Decimal] | None
    open_order_notional_base: Decimal | None
    daily_realised_pnl_base: Decimal | None
    daily_total_pnl_base: Decimal | None
    equity_high_water_mark_base: Decimal | None
    strategy_exposure_base: dict[str, Decimal] | None = None
    market_exposure_base: dict[str, Decimal] | None = None
    currency_exposure_base: dict[str, Decimal] | None = None
    estimated_fees_base: Decimal = Decimal("0")
    seen_proposal_ids: frozenset[str] = frozenset()
    trace_id: str | None = None
    shadow_mode: bool = False

    def __post_init__(self):
        object.__setattr__(self, "now", utc_datetime(self.now, "now"))

    def canonical_payload(self) -> dict[str, Any]:
        return json_value(asdict(self))

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RiskFinding:
    check: str
    status: str
    reason_code: str
    summary: str
    observed: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class RiskDecision:
    decision_id: str
    proposal_id: str
    status: DecisionStatus
    approved: bool
    timestamp: datetime
    expires_at: datetime
    primary_reason_code: str
    summary: str
    findings: tuple[RiskFinding, ...]
    checks_performed: tuple[str, ...]
    checks_passed: tuple[str, ...]
    checks_failed: tuple[str, ...]
    checks_unavailable: tuple[str, ...]
    relevant_limits: dict[str, Any]
    observed_values: dict[str, Any]
    software_version: str
    configuration_version: str
    configuration_hash: str
    proposal_fingerprint: str
    context_fingerprint: str
    accounting_generation_id: str | None
    market_data_timestamps: dict[str, str | None]
    correlation_id: str
    evaluation_latency_ms: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RiskDecision":
        data = dict(payload)
        data["status"] = DecisionStatus(data["status"])
        data["timestamp"] = utc_datetime(data["timestamp"], "timestamp")
        data["expires_at"] = utc_datetime(data["expires_at"], "expires_at")
        data["findings"] = tuple(RiskFinding(**item) for item in data.get("findings", []))
        for name in ("checks_performed", "checks_passed", "checks_failed", "checks_unavailable"):
            data[name] = tuple(data.get(name, []))
        return cls(**data)
