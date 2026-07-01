from copy import deepcopy

from research.parameter_schema import (
    PARAMETER_ALIASES,
    PARAMETER_SCHEMA,
    parameter_default,
)

DEFAULT_RESEARCH_CONFIG = {
    key: parameter_default(key)
    for key in PARAMETER_SCHEMA
}


def _live_config_to_dict(live_config):
    if live_config is None:
        return {}

    if isinstance(live_config, dict):
        return deepcopy(live_config)

    result = {}

    for name in dir(live_config):
        if name.startswith("_"):
            continue

        value = getattr(live_config, name)

        if callable(value):
            continue

        result[name] = deepcopy(value)

    return result


def _clean_value(value):
    if value in ("", "Not configured", "None"):
        return None

    return value


def _as_int(value):
    value = _clean_value(value)

    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return None


def _as_float(value):
    value = _clean_value(value)

    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def _normalise_percent(value):
    value = _as_float(value)

    if value is None:
        return None

    if value > 1:
        return value / 100

    return value


def build_experiment_config(live_config, experiment_params):
    """Build an isolated research config without mutating live settings."""
    research_config = _live_config_to_dict(live_config)

    for key, value in DEFAULT_RESEARCH_CONFIG.items():
        research_config.setdefault(key, deepcopy(value))

    experiment_params = experiment_params or {}

    for source_key, value in experiment_params.items():
        target_key = PARAMETER_ALIASES.get(source_key)

        if target_key is None:
            continue

        metadata = PARAMETER_SCHEMA[target_key]

        if metadata["type"] == "integer":
            research_config[target_key] = _as_int(value)
        elif target_key in {
            "position_size",
            "stop_loss_pct",
            "take_profit_pct",
        }:
            research_config[target_key] = _normalise_percent(value)
        elif metadata["type"] == "float":
            research_config[target_key] = _as_float(value)
        elif metadata["type"] == "select":
            cleaned = _clean_value(value)
            research_config[target_key] = (
                cleaned
                if cleaned in metadata["options"]
                else metadata["default"]
            )

    return research_config
