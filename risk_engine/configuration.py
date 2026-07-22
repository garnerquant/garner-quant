from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from risk_engine.models import decimal_value


DEFAULT_CONFIG_PATH = Path(__file__).with_name("risk_config.json")


class RiskConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RiskConfiguration:
    schema_version: str
    configuration_version: str
    base_currency: str
    trading_enabled: bool
    limits_approved: bool
    decision_expiry_seconds: int
    maximum_order_notional_base: Decimal
    maximum_position_notional_base: Decimal
    maximum_position_ratio: Decimal
    maximum_gross_exposure_ratio: Decimal
    maximum_net_exposure_ratio: Decimal
    maximum_open_positions: int
    maximum_strategy_exposure_ratio: Decimal
    maximum_market_exposure_ratio: Decimal
    maximum_currency_exposure_ratio: Decimal
    maximum_daily_realised_loss_base: Decimal
    maximum_daily_total_loss_base: Decimal
    maximum_drawdown_ratio: Decimal
    market_data_max_age_seconds: dict[str, int]
    fx_max_age_seconds: dict[str, int]
    allowed_order_types: tuple[str, ...]
    allowed_time_in_force: tuple[str, ...]
    reduction_orders_allowed_when_limits_exceeded: bool
    kill_switch_allows_reductions: bool
    configuration_hash: str

    def limits(self) -> dict[str, Any]:
        return {
            "maximum_order_notional_base": str(self.maximum_order_notional_base),
            "maximum_position_notional_base": str(self.maximum_position_notional_base),
            "maximum_position_ratio": str(self.maximum_position_ratio),
            "maximum_gross_exposure_ratio": str(self.maximum_gross_exposure_ratio),
            "maximum_net_exposure_ratio": str(self.maximum_net_exposure_ratio),
            "maximum_open_positions": self.maximum_open_positions,
            "maximum_strategy_exposure_ratio": str(self.maximum_strategy_exposure_ratio),
            "maximum_market_exposure_ratio": str(self.maximum_market_exposure_ratio),
            "maximum_currency_exposure_ratio": str(self.maximum_currency_exposure_ratio),
            "maximum_daily_realised_loss_base": str(self.maximum_daily_realised_loss_base),
            "maximum_daily_total_loss_base": str(self.maximum_daily_total_loss_base),
            "maximum_drawdown_ratio": str(self.maximum_drawdown_ratio),
        }


REQUIRED_FIELDS = {
    "schema_version", "configuration_version", "base_currency", "trading_enabled",
    "limits_approved", "decision_expiry_seconds", "maximum_order_notional_base",
    "maximum_position_notional_base", "maximum_position_ratio",
    "maximum_gross_exposure_ratio", "maximum_net_exposure_ratio",
    "maximum_open_positions", "maximum_strategy_exposure_ratio",
    "maximum_market_exposure_ratio", "maximum_currency_exposure_ratio",
    "maximum_daily_realised_loss_base", "maximum_daily_total_loss_base",
    "maximum_drawdown_ratio", "market_data_max_age_seconds", "fx_max_age_seconds",
    "allowed_order_types", "allowed_time_in_force",
    "reduction_orders_allowed_when_limits_exceeded", "kill_switch_allows_reductions",
}


def load_risk_configuration(path=DEFAULT_CONFIG_PATH) -> RiskConfiguration:
    path = Path(path)
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RiskConfigurationError("risk configuration is missing or malformed") from exc
    if not isinstance(payload, dict):
        raise RiskConfigurationError("risk configuration must be an object")
    missing = REQUIRED_FIELDS - set(payload)
    unknown = set(payload) - REQUIRED_FIELDS
    if missing or unknown:
        raise RiskConfigurationError(
            f"risk configuration fields invalid; missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    if payload["schema_version"] != "1.0" or payload["base_currency"] != "GBP":
        raise RiskConfigurationError("risk configuration schema/base currency is unsupported")
    if type(payload["trading_enabled"]) is not bool or type(payload["limits_approved"]) is not bool:
        raise RiskConfigurationError("risk configuration booleans are invalid")
    integer_fields = ("decision_expiry_seconds", "maximum_open_positions")
    if any(type(payload[name]) is not int or payload[name] <= 0 for name in integer_fields):
        raise RiskConfigurationError("risk configuration positive integers are invalid")
    decimal_fields = [name for name in REQUIRED_FIELDS if name.startswith("maximum_") and name != "maximum_open_positions"]
    decimals = {name: decimal_value(payload[name], name) for name in decimal_fields}
    if any(value <= 0 for value in decimals.values()):
        raise RiskConfigurationError("risk limits must be positive")
    for name in ("maximum_position_ratio", "maximum_gross_exposure_ratio", "maximum_net_exposure_ratio",
                 "maximum_strategy_exposure_ratio", "maximum_market_exposure_ratio",
                 "maximum_currency_exposure_ratio", "maximum_drawdown_ratio"):
        if decimals[name] > 1:
            raise RiskConfigurationError(f"{name} must be a decimal ratio no greater than 1")
    for mapping_name in ("market_data_max_age_seconds", "fx_max_age_seconds"):
        mapping = payload[mapping_name]
        if not isinstance(mapping, dict) or not mapping or any(type(v) is not int or v <= 0 for v in mapping.values()):
            raise RiskConfigurationError(f"{mapping_name} is invalid")
    digest = hashlib.sha256(raw).hexdigest()
    return RiskConfiguration(
        schema_version=payload["schema_version"],
        configuration_version=str(payload["configuration_version"]),
        base_currency=payload["base_currency"],
        trading_enabled=payload["trading_enabled"],
        limits_approved=payload["limits_approved"],
        decision_expiry_seconds=payload["decision_expiry_seconds"],
        maximum_order_notional_base=decimals["maximum_order_notional_base"],
        maximum_position_notional_base=decimals["maximum_position_notional_base"],
        maximum_position_ratio=decimals["maximum_position_ratio"],
        maximum_gross_exposure_ratio=decimals["maximum_gross_exposure_ratio"],
        maximum_net_exposure_ratio=decimals["maximum_net_exposure_ratio"],
        maximum_open_positions=payload["maximum_open_positions"],
        maximum_strategy_exposure_ratio=decimals["maximum_strategy_exposure_ratio"],
        maximum_market_exposure_ratio=decimals["maximum_market_exposure_ratio"],
        maximum_currency_exposure_ratio=decimals["maximum_currency_exposure_ratio"],
        maximum_daily_realised_loss_base=decimals["maximum_daily_realised_loss_base"],
        maximum_daily_total_loss_base=decimals["maximum_daily_total_loss_base"],
        maximum_drawdown_ratio=decimals["maximum_drawdown_ratio"],
        market_data_max_age_seconds=dict(payload["market_data_max_age_seconds"]),
        fx_max_age_seconds=dict(payload["fx_max_age_seconds"]),
        allowed_order_types=tuple(str(v).upper() for v in payload["allowed_order_types"]),
        allowed_time_in_force=tuple(str(v).upper() for v in payload["allowed_time_in_force"]),
        reduction_orders_allowed_when_limits_exceeded=bool(payload["reduction_orders_allowed_when_limits_exceeded"]),
        kill_switch_allows_reductions=bool(payload["kill_switch_allows_reductions"]),
        configuration_hash=digest,
    )
