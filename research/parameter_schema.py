PARAMETER_SCHEMA = {
    "technical_score_threshold": {
        "display_name": "Technical Score Threshold",
        "experiment_name": "Technical score threshold",
        "type": "integer",
        "minimum": 0,
        "maximum": 5,
        "step": 1,
        "default": 3,
        "description": (
            "Production technical_score is a component count from 0 to 5; "
            "live signals currently require score >= 3."
        ),
    },
    "max_positions": {
        "display_name": "Max Positions",
        "experiment_name": "Maximum positions",
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "step": 1,
        "default": 5,
        "description": "Maximum simultaneous open positions in the research simulation.",
    },
    "position_size": {
        "display_name": "Position Size %",
        "experiment_name": "Position size",
        "type": "float",
        "minimum": 0.0,
        "maximum": 100.0,
        "step": 1.0,
        "default": 0.0,
        "description": (
            "Optional fixed research position size as a percentage of starting cash. "
            "Zero means use live-rule weights."
        ),
    },
    "stop_loss_pct": {
        "display_name": "Stop Loss %",
        "experiment_name": "Stop loss %",
        "type": "float",
        "minimum": 0.0,
        "maximum": 100.0,
        "step": 0.5,
        "default": 0.0,
        "description": "Optional fixed stop loss percentage for research runs.",
    },
    "take_profit_pct": {
        "display_name": "Take Profit %",
        "experiment_name": "Take profit %",
        "type": "float",
        "minimum": 0.0,
        "maximum": 100.0,
        "step": 0.5,
        "default": 0.0,
        "description": "Optional fixed take profit percentage for research runs.",
    },
    "min_volume": {
        "display_name": "Minimum Volume",
        "experiment_name": "Minimum volume",
        "type": "float",
        "minimum": 0.0,
        "maximum": None,
        "step": 1000.0,
        "default": 0.0,
        "description": "Optional minimum volume filter when saved volume data is available.",
    },
    "exit_mode": {
        "display_name": "Exit Mode",
        "experiment_name": "Exit mode",
        "type": "select",
        "options": ["signals_and_stops", "stops_only", "signal_only"],
        "default": "signals_and_stops",
        "description": "Research-only exit rule mode.",
    },
}


PARAMETER_ALIASES = {
    key: key for key in PARAMETER_SCHEMA
}

for key, metadata in PARAMETER_SCHEMA.items():
    PARAMETER_ALIASES[metadata["display_name"]] = key
    PARAMETER_ALIASES[metadata["experiment_name"]] = key


def parameter_metadata(key):
    return PARAMETER_SCHEMA[key]


def experiment_parameter_name(key):
    return PARAMETER_SCHEMA[key]["experiment_name"]


def parameter_default(key):
    return PARAMETER_SCHEMA[key]["default"]


def supported_parameter_keys():
    return list(PARAMETER_SCHEMA.keys())
