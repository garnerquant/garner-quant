from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from canonical_accounting.currency import canonical_currency, decimal_value


class AccountingEventError(ValueError):
    pass


class AccountingEventType(str, Enum):
    BUY_FILL = "BUY_FILL"
    SELL_FILL = "SELL_FILL"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    FEE = "FEE"
    DIVIDEND = "DIVIDEND"
    FX_ADJUSTMENT = "FX_ADJUSTMENT"
    CORPORATE_ACTION = "CORPORATE_ACTION"


@dataclass(frozen=True)
class AccountingEvent:
    event_id: str
    event_type: AccountingEventType
    timestamp: datetime
    strategy_id: str
    instrument: str
    currency: str
    amount: Decimal
    quantity: Decimal
    reference_generation: str
    correlation_id: str
    source: str
    fx_rate_to_base: Decimal = Decimal("1")
    fx_timestamp: datetime | None = None
    fx_source: str = "identity"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, **values):
        data = dict(values)
        data.setdefault("fx_rate_to_base", Decimal("1"))
        data.setdefault("fx_timestamp", None)
        data.setdefault("fx_source", "identity")
        data.setdefault("metadata", {})
        try:
            data["event_type"] = AccountingEventType(data["event_type"])
        except Exception as exc:
            raise AccountingEventError("unsupported accounting event type") from exc
        for name in ("amount", "quantity", "fx_rate_to_base"):
            data[name] = decimal_value(data.get(name), name)
        timestamp = data.get("timestamp")
        if not isinstance(timestamp, datetime):
            timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise AccountingEventError("event timestamp must be timezone-aware")
        data["timestamp"] = timestamp.astimezone(timezone.utc)
        fx_timestamp = data.get("fx_timestamp")
        if fx_timestamp is not None and not isinstance(fx_timestamp, datetime):
            fx_timestamp = datetime.fromisoformat(str(fx_timestamp).replace("Z", "+00:00"))
        if fx_timestamp is not None:
            if fx_timestamp.tzinfo is None:
                raise AccountingEventError("FX timestamp must be timezone-aware")
            data["fx_timestamp"] = fx_timestamp.astimezone(timezone.utc)
        event = cls(**data)
        event.validate()
        return event

    def validate(self):
        required = (self.event_id, self.strategy_id, self.instrument, self.reference_generation,
                    self.correlation_id, self.source)
        if any(not str(value).strip() for value in required):
            raise AccountingEventError("event identity fields are required")
        canonical_currency(self.currency)
        if self.amount < 0 or self.quantity < 0 or self.fx_rate_to_base <= 0:
            raise AccountingEventError("event amount/quantity/FX values are invalid")
        if self.currency != "GBP" and (self.fx_timestamp is None or not self.fx_source.strip()):
            raise AccountingEventError("foreign-currency event requires verified FX metadata")
        if self.currency == "GBP" and self.fx_rate_to_base != Decimal("1"):
            raise AccountingEventError("GBP events require identity FX")
        if self.event_type in {AccountingEventType.BUY_FILL, AccountingEventType.SELL_FILL}:
            if self.quantity <= 0 or self.amount <= 0:
                raise AccountingEventError("fill quantity and unit price must be positive")
        elif self.event_type in {AccountingEventType.DEPOSIT, AccountingEventType.WITHDRAWAL,
                                 AccountingEventType.FEE, AccountingEventType.DIVIDEND}:
            if self.amount <= 0 or self.quantity != 0:
                raise AccountingEventError("cash event requires positive amount and zero quantity")
        elif self.event_type is AccountingEventType.FX_ADJUSTMENT:
            if self.quantity != 0 or self.amount <= 0:
                raise AccountingEventError("FX adjustment requires positive rate and zero quantity")
        elif self.event_type is AccountingEventType.CORPORATE_ACTION:
            if self.metadata.get("action") != "SPLIT" or self.amount <= 0 or self.quantity != 0:
                raise AccountingEventError("only explicit positive split-factor corporate actions are supported")

    def to_dict(self):
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        payload["timestamp"] = self.timestamp.isoformat()
        payload["fx_timestamp"] = self.fx_timestamp.isoformat() if self.fx_timestamp else None
        for name in ("amount", "quantity", "fx_rate_to_base"):
            payload[name] = str(payload[name])
        return payload

    @property
    def fingerprint(self):
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, payload):
        return cls.create(**payload)
