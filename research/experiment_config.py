from copy import deepcopy


DEFAULT_RESEARCH_CONFIG = {
    "technical_score_threshold": 3,
    "max_positions": None,
    "position_size": None,
    "stop_loss_pct": None,
    "take_profit_pct": None,
    "min_volume": None,
    "exit_mode": "signals_and_stops",
}


PARAMETER_ALIASES = {
    "Technical score threshold": "technical_score_threshold",
    "technical_score_threshold": "technical_score_threshold",
    "Maximum positions": "max_positions",
    "max_positions": "max_positions",
    "Position size": "position_size",
    "position_size": "position_size",
    "Stop loss %": "stop_loss_pct",
    "stop_loss_pct": "stop_loss_pct",
    "Take profit %": "take_profit_pct",
    "take_profit_pct": "take_profit_pct",
    "Minimum volume": "min_volume",
    "min_volume": "min_volume",
    "Exit mode": "exit_mode",
    "exit_mode": "exit_mode",
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

        if target_key in {
            "technical_score_threshold",
            "max_positions",
        }:
            research_config[target_key] = _as_int(value)
        elif target_key in {
            "position_size",
            "stop_loss_pct",
            "take_profit_pct",
        }:
            research_config[target_key] = _normalise_percent(value)
        elif target_key == "min_volume":
            research_config[target_key] = _as_float(value)
        elif target_key == "exit_mode":
            research_config[target_key] = _clean_value(value) or "signals_and_stops"

    return research_config
